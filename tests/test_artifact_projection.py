"""Artifact-only closures pass normal safety gates without altering legacy bytes."""

import copy
from pathlib import Path
from typing import Any

import pytest
from artifact_helpers import index_at, tar_files
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.artifact import artifact_name
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.legacy import legacy_documents
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.selection.load import load_inputs


@pytest.fixture(params=["local", "mapped"])
def projection_repo(
    tmp_path: Path, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, dict[str, Path]]:
    """Provide equivalent local and mapped resource graphs with a transitive cycle.

    Args:
        tmp_path: Isolated publication directory.
        request: Whether the source is local or mapped.
        monkeypatch: Network guard.

    Returns:
        Catalog, actual source and explicit offline roots.
    """

    def forbidden(*_args: object, **_kwargs: object) -> None:
        """Projection tests must never acquire inputs."""
        pytest.fail("Projection tests must remain offline")

    monkeypatch.setattr("socket.socket.connect", forbidden)
    root = tmp_path / "catalog"
    source = root if request.param == "local" else tmp_path / "vendor"
    root.mkdir()
    (source / "skills/entry").mkdir(parents=True)
    (source / "skills/entry/SKILL.md").write_text(
        "---\nname: entry\ndescription: Projection.\n---\n"
        "[Guide](../../shared/readme.md)\n"
    )
    (source / "shared/data").mkdir(parents=True)
    (source / "shared/data/input.txt").write_text("Transitive resource bytes.\n")
    (source / "shared/readme.md").write_text("[Details](details.md)\n")
    (source / "shared/details.md").write_text(
        "[Data directory](data/)\n[Cycle](readme.md)\n"
        "[Capability](../skills/entry/SKILL.md)\n"
    )
    (source / "shared/config.json").write_text('{"leaf": "data/input.txt"}\n')
    projection = {
        "version": 1,
        "resources": [
            {"id": "readme", "path": "shared/readme.md"},
            {"id": "details", "path": "shared/details.md"},
            {"id": "data", "path": "shared/data"},
            {
                "id": "config",
                "path": "shared/config.json",
                "x-resource-paths": {"config.json": ["/leaf"]},
            },
        ],
        "bindings": {"skill/entry": ["readme", "details", "data", "config"]},
    }
    document: dict[str, Any] = {
        "apiVersion": "ai-skills.dev/v1",
        "publisher": {"id": "catalog", "repo": "fixture/catalog"},
        "policy": {"provenance": {"mode": "strict"}},
    }
    if source == root:
        document["packages"] = [
            {
                "id": "tools",
                "capabilities": [{"id": "entry", "path": "skills/entry"}],
                "artifactResources": projection,
            }
        ]
        document["exports"] = ["tools"]
        roots = {}
    else:
        document["vendors"] = [
            {
                "id": "vendor",
                "repo": "fixture/vendor",
                "sha": "a" * 40,
                "mapping": {
                    "skillRoots": ["skills"],
                    "packages": [
                        {
                            "id": "tools",
                            "skillsRoot": "skills",
                            "skills": "*",
                            "artifactResources": projection,
                        }
                    ],
                },
            }
        ]
        document["exports"] = ["vendor/tools"]
        roots = {"vendor": source}
    (root / "ai-skills.yaml").write_text(dump_document(document))
    return root, source, roots


def _package(document: dict[str, Any]) -> dict[str, Any]:
    """Locate the equivalent publication declaration in either fixture.

    Args:
        document: Local or manifestless-vendor publication.

    Returns:
        Package owning the artifact-only closure.
    """
    if "packages" in document:
        return dict(document["packages"][0])
    return dict(document["vendors"][0]["mapping"]["packages"][0])


def _args(root: Path, roots: dict[str, Path], command: str = "lock") -> list[str]:
    """Build public CLI arguments for explicit offline inputs.

    Args:
        root: Catalog root.
        roots: Declared vendor snapshots.
        command: ``lock`` or the explicit-input ``artifacts`` writer.

    Returns:
        Public arguments that seed snapshots without acquisition.
    """
    prefix = ["bake", "artifacts"] if command == "artifacts" else [command]
    return ["--repo-root", str(root), *prefix] + [
        value
        for name, path in roots.items()
        for value in ("--vendor-tree", f"{name}={path}")
    ]


def test_complete_projection_rewrites_and_preserves_legacy_contract(
    projection_repo: tuple[Path, Path, dict[str, Path]],
) -> None:
    """Transitive cycles/directories relocate while ordinary legacy checks remain."""
    root, source, roots = projection_repo
    path = root / "ai-skills.yaml"
    document = read_document(path)
    before = copy.deepcopy(document)
    package = _package(before)
    package.pop("artifactResources")
    if "packages" in before:
        before["packages"][0] = package
    else:
        before["vendors"][0]["mapping"]["packages"][0] = package
    assert_that(legacy_documents(document)).is_equal_to(legacy_documents(before))
    assert_that(cli.main(_args(root, roots))).is_zero()
    for command in (["lock", "--check"], ["build"]):
        assert_that(cli.main(["--repo-root", str(root), *command])).is_zero()
    inventory, selection = load_inputs(root, vendor_roots=roots)
    assert_that(selection.valid).is_true()
    assert_that(inventory.resources).is_length(4)
    output = root / "dist/artifacts"
    package_index = index_at(output)["packages"][0]
    capability = package_index["capabilities"][0]
    assert_that(capability["portability"]).is_empty()
    assert_that(capability["resources"]).is_length(4)
    files = tar_files(output / artifact_name(package_index["id"]))
    assert_that(
        any(name.endswith("/shared/data/input.txt") for name in files)
    ).is_true()
    skill = files[capability["path"] + "/SKILL.md"][0].decode()
    assert_that(skill).contains("_shared/", "shared/readme.md")
    assert_that((source / "shared/details.md").read_text()).contains(
        "[Cycle](readme.md)"
    )
    if source == root:
        offline = ["--repo-root", str(root), "lock", "--check", "--inputs-only"]
        assert_that(cli.main(offline)).is_zero()
        (source / "shared/data/input.txt").write_text("Changed transitive input.\n")
        assert_that(cli.main(offline)).is_equal_to(1)


@pytest.mark.parametrize(
    "control",
    [
        "binding-leaf",
        "declaration-leaf",
        "binding-details",
        "scalar-target",
        "scalar-file",
        "escape",
        "symlink",
        "unknown-binding",
        "unknown-resource",
        "unused-resource",
        "duplicate-resource",
        "unknown-version",
    ],
)
def test_incomplete_projection_fails_before_replacing_artifacts(
    projection_repo: tuple[Path, Path, dict[str, Path]],
    capsys: pytest.CaptureFixture[str],
    control: str,
) -> None:
    """No transitive omission, forged field or unsafe target can publish."""
    root, source, roots = projection_repo
    assert_that(cli.main(_args(root, roots))).is_zero()
    assert_that(cli.main(["--repo-root", str(root), "build"])).is_zero()
    capsys.readouterr()
    output = root / "dist/artifacts"
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    commitment = (root / "ai-skills.lock").read_bytes()
    path = root / "ai-skills.yaml"
    document = read_document(path)
    package = _package(document)
    projection = package["artifactResources"]
    binding = projection["bindings"]["skill/entry"]
    if control in {"binding-leaf", "declaration-leaf"}:
        binding.remove("data")
        if control == "declaration-leaf":
            projection["resources"] = [
                r for r in projection["resources"] if r["id"] != "data"
            ]
    elif control == "binding-details":
        binding.remove("details")
    elif control == "scalar-target":
        (source / "shared/config.json").write_text('{"leaf": "../undeclared.txt"}')
        (source / "undeclared.txt").write_text("Existing but undeclared.\n")
    elif control == "scalar-file":
        projection["resources"][-1]["x-resource-paths"] = {"absent.json": ["/leaf"]}
    elif control == "escape":
        (source / "shared/details.md").write_text(
            "[Escape](../../catalog/ai-skills.yaml)\n"
        )
    elif control == "symlink":
        target = source / "shared/data/input.txt"
        target.unlink()
        target.symlink_to("../readme.md")
    elif control == "unknown-binding":
        projection["bindings"]["skill/absent"] = binding[:]
    elif control == "unknown-resource":
        binding.append("absent")
    elif control == "unused-resource":
        projection["resources"].append({"id": "unused", "path": "shared/config.json"})
    elif control == "duplicate-resource":
        projection["resources"].append(projection["resources"][0])
    else:
        projection["version"] = 2
    if "packages" in document:
        document["packages"][0] = package
    else:
        document["vendors"][0]["mapping"]["packages"][0] = package
    path.write_text(dump_document(document))
    # The explicit writer reports the projection failure itself; lock and
    # build must also fail without replacing the lock or published artifacts.
    assert_that(cli.main(_args(root, roots, "artifacts"))).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("artifacts: ")
    assert_that(cli.main(_args(root, roots))).is_equal_to(1)
    assert_that(capsys.readouterr().err).is_not_empty()
    # Mutating vendor bytes behind an unchanged pin cannot reach the frozen
    # build: it rebuilds the reviewed cached source and republishes identical
    # bytes. Every other control fails the offline build closed.
    vendor_only = source != root and control in {"scalar-target", "escape", "symlink"}
    assert_that(cli.main(["--repo-root", str(root), "build"])).is_equal_to(
        int(not vendor_only)
    )
    assert_that(
        {path.name: path.read_bytes() for path in output.iterdir()}
    ).is_equal_to(before)
    assert_that((root / "ai-skills.lock").read_bytes()).is_equal_to(commitment)
