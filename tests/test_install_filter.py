"""Subtractive filtering, closure checks and origin denies over built artifacts."""

import json
import shutil
import subprocess  # nosec B404 - fixed interpreter argv, no shell
import sys
from pathlib import Path
from typing import Any

import pytest
from artifact_helpers import bake_fixture
from assertpy import assert_that
from install_helpers import (
    GOLDEN,
    X_ORIGIN,
    build_two_hop,
    builder_kept,
    expected_cases,
    forbid_resolution,
    run,
)

from ai_skills_engine.install.errors import InstallError
from ai_skills_engine.install.filter import ClosureError, filter_inventory
from ai_skills_engine.install.inventory import merge_indexes
from ai_skills_engine.install.legacy import select_packages
from ai_skills_engine.install.selectors import DenyRule, parse_selector
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document

pytest_plugins = ["artifact_helpers", "install_helpers"]
CASES = expected_cases()
Z_REQUIRING_X = ("first", "helper", "second")


def _cli_args(case: dict[str, Any]) -> list[str]:
    """Translate a recorded case into install flags.

    Args:
        case: Expected-kept case.

    Returns:
        ``--exclude``/``--deny-origin`` arguments.
    """
    args = []
    for item in case["exclude"]:
        args += ["--exclude", item]
    for item in case["deny"]:
        args += ["--deny-origin", item]
    return args


@pytest.mark.parametrize("case", CASES, ids=[item["name"] for item in CASES])
def test_install_agrees_with_builder_recorded_kept_sets(
    case: dict[str, Any],
    artifact_repo: Path,
    tmp_path: Path,
    consumer: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The install entry point, the builder and the recorded golden agree."""
    path = artifact_repo / "ai-skills.yaml"
    document = read_document(path)
    document["packages"][0]["exclude"] = case["builder"]["exclude"]
    document.setdefault("policy", {})["deny"] = {"origins": case["builder"]["deny"]}
    path.write_text(dump_document(document))
    built = tmp_path / "builder"
    if "error" in case:
        with pytest.raises(ValueError, match="Artifact selection failed"):
            bake_fixture(root=artifact_repo, destination=built)
    else:
        bake_fixture(root=artifact_repo, destination=built)
        assert_that(builder_kept(built)).is_equal_to(case["kept"])
    forbid_resolution(monkeypatch)
    status, report, err = run(
        capsys, "install", "--artifacts", str(GOLDEN), "--dry-run", *_cli_args(case)
    )
    if "error" in case:
        assert_that(status).is_equal_to(1)
        assert_that(err).contains(case["error"]["chain"])
        for item in case["error"]["suggest"]:
            assert_that(err).contains(f"--exclude {item}")
    else:
        assert_that(status).is_zero()
        assert_that(report).is_not_none()
        assert_that(report["kept"] if report else None).is_equal_to(case["kept"])


def test_excluding_a_requirement_reports_full_chain(tmp_path: Path) -> None:
    """Multi-hop chains come from embedded direct edges; fixes name every root."""
    artifacts = build_two_hop(tmp_path / "src", tmp_path / "out")
    inventory = merge_indexes([json.loads((artifacts / "index.json").read_text())])
    with pytest.raises(ClosureError) as raised:
        filter_inventory(
            inventory,
            excludes=[parse_selector("capability:y/tools:skill/renamed")],
            denies=[],
        )
    assert_that(raised.value.suggestions).is_equal_to(
        ("capability:z/tools:skill/first",)
    )
    assert_that(str(raised.value)).contains(
        "z/tools:skill/first -> y/tools:skill/renamed"
    )


@pytest.mark.parametrize("hop", ["github.com/fixture/x", "github.com/fixture/x*"])
def test_reexported_origin_is_denied_through_every_hop(
    tmp_path: Path, hop: str
) -> None:
    """X re-exported by Y then Z: X capabilities and X `_shared` copies are denied."""
    artifacts = build_two_hop(tmp_path / "src", tmp_path / "out")
    index = json.loads((artifacts / "index.json").read_text())
    chains = {
        item["id"]: [
            step["origin"] for chain in item["lineage"] for step in chain["lineage"]
        ]
        for package in index["packages"]
        for item in package["capabilities"]
    }
    assert_that(chains["x/tools:skill/plain"]).is_equal_to(
        [X_ORIGIN, "github.com/fixture/y", "github.com/fixture/z"]
    )
    inventory = merge_indexes([index])
    rule = [DenyRule(origin=hop, source="--deny-origin")]
    with pytest.raises(ClosureError) as raised:
        filter_inventory(inventory, excludes=[], denies=rule)
    by_capability = {item.capability: item for item in raised.value.violations}
    helper = by_capability["z/tools:skill/helper"]
    assert_that(helper.target).is_equal_to("x/tools:resource/script")
    assert_that(helper.reason).contains("denied origin github.com/fixture/")
    assert_that(sorted(by_capability)).is_equal_to(
        [f"z/tools:skill/{name}" for name in Z_REQUIRING_X]
    )
    excludes = [parse_selector(f"capability:z/tools:skill/{n}") for n in Z_REQUIRING_X]
    result = filter_inventory(inventory, excludes=excludes, denies=rule)
    assert_that(result.capabilities).is_equal_to(("z/tools:skill/own",))
    assert_that(result.resources).is_empty()
    assert_that(result.removed).contains_key(
        "x/tools:skill/plain",
        "y/tools:skill/renamed",
        "y/tools:skill/transformed",
        "x/tools:resource/script",
    )


def test_reexport_deny_agrees_with_builder(tmp_path: Path) -> None:
    """The builder applying the same deny and excludes records the same kept set."""
    full = build_two_hop(tmp_path / "full-src", tmp_path / "full")

    def veto(document: dict[str, Any], z: Path) -> None:
        """Apply the consumer selection on the build plane.

        Args:
            document: Z manifest.
            z: Z snapshot root (unchanged).
        """
        del z
        document["policy"]["deny"] = {"origins": [X_ORIGIN]}
        document["packages"][0]["exclude"] = [
            f"z/tools:skill/{name}" for name in Z_REQUIRING_X
        ]

    vetoed = build_two_hop(tmp_path / "veto-src", tmp_path / "veto", veto)
    excludes = [parse_selector(f"capability:z/tools:skill/{n}") for n in Z_REQUIRING_X]
    result = filter_inventory(
        merge_indexes([json.loads((full / "index.json").read_text())]),
        excludes=excludes,
        denies=[DenyRule(origin=X_ORIGIN, source="--deny-origin")],
    )
    assert_that(builder_kept(vetoed)).is_equal_to(
        {"capabilities": list(result.capabilities), "resources": list(result.resources)}
    )


def test_cli_denies_reexported_origin_from_verified_tars(
    tmp_path: Path, consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end: digests verified, then X denied in every tar's embedded index."""
    artifacts = build_two_hop(tmp_path / "src", tmp_path / "out")
    status, _, err = run(
        capsys, "install", "--artifacts", str(artifacts), "--deny-origin", X_ORIGIN
    )
    assert_that(status).is_equal_to(1)
    assert_that(err).contains(
        "z/tools:skill/helper -> x/tools:resource/script",
        "--exclude capability:z/tools:skill/first",
    )
    excludes = [f"--exclude=capability:z/tools:skill/{n}" for n in Z_REQUIRING_X]
    status, report, _ = run(
        capsys,
        "install",
        "--artifacts",
        str(artifacts),
        "--deny-origin",
        X_ORIGIN,
        *excludes,
    )
    assert_that(status).is_zero()
    assert_that(report["kept"] if report else None).is_equal_to(
        {"capabilities": ["z/tools:skill/own"], "resources": []}
    )


def _strip(index: dict[str, Any], field: str) -> dict[str, Any]:
    """Remove embedded facts the plane needs, bypassing schema checks.

    Args:
        index: Golden catalog index.
        field: What to break.

    Returns:
        Broken index.
    """
    capability = index["packages"][0]["capabilities"][0]
    if field == "lineage":
        capability["lineage"] = []
    elif field == "resource-lineage":
        capability["resources"][0]["lineage"] = [
            {"id": "x/y:resource/z", "lineage": []}
        ]
    else:
        capability["closure"]["capabilities"].append("fixture/tools:skill/absent")
    return index


@pytest.mark.parametrize("field", ["lineage", "resource-lineage", "closure"])
def test_missing_metadata_fails_closed(field: str) -> None:
    """Missing lineage or a dangling closure ID stops the install."""
    index = _strip(json.loads((GOLDEN / "index.json").read_text()), field)
    with pytest.raises(InstallError, match="missing lineage|absent from the artifact"):
        merge_indexes([index])


def test_conflicting_records_across_tars_fail_closed() -> None:
    """Two artifacts may not disagree about one capability."""
    index = json.loads((GOLDEN / "index.json").read_text())
    other = json.loads(json.dumps(index))
    other["packages"][0]["capabilities"][0]["license"] = "MIT"
    with pytest.raises(InstallError, match="disagree about capability"):
        merge_indexes([index, other])


def test_filter_output_depends_only_on_index_and_profile(
    tmp_path: Path,
    consumer: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With resolver/network boundaries failing, results ignore cwd, env and lock."""
    artifacts = build_two_hop(tmp_path / "src", tmp_path / "out")
    forbid_resolution(monkeypatch)
    args = ["install", "--artifacts", str(artifacts), "--dry-run"]
    args += [
        f"--exclude=capability:y/tools:skill/{n}" for n in ("renamed", "transformed")
    ]
    args += [
        "--exclude=capability:z/tools:skill/first",
        "--exclude=capability:z/tools:skill/second",
    ]
    first = run(capsys, *args)
    noise = tmp_path / "noise"
    shutil.copytree(tmp_path / "src", noise)
    monkeypatch.chdir(noise / "z")
    monkeypatch.setenv("AI_SKILLS_CACHE", str(tmp_path / "absent-cache"))
    monkeypatch.setenv("GITHUB_TOKEN", "unused")
    second = run(capsys, *args)
    assert_that(first[0]).is_zero()
    assert_that(second).is_equal_to(first)
    assert_that(first[1]["kept"]["capabilities"] if first[1] else None).is_equal_to(
        ["x/tools:skill/plain", "z/tools:skill/helper", "z/tools:skill/own"]
    )


def test_install_package_imports_no_build_plane_resolution() -> None:
    """The install entry point cannot reach resolution: none of it is importable."""
    program = (
        "import sys, json, ai_skills_engine.install.cli;"
        "print(json.dumps(sorted(sys.modules)))"
    )
    loaded = json.loads(
        subprocess.run(  # nosec B603 - fixed interpreter argv
            [sys.executable, "-c", program], check=True, capture_output=True, text=True
        ).stdout
    )
    forbidden = (
        "ai_skills_engine.selection",
        "ai_skills_engine.source_cache",
        "ai_skills_engine.commands",
        "ai_skills_engine.artifact",
        "ai_skills_engine.artifacts",
        "ai_skills_engine.inventory",
        "ai_skills_engine.provenance.build",
        "ai_skills_engine.repin",
        "ai_skills_engine.bake",
        "http.client",
        "urllib.request",
        "socket",
    )
    assert_that([name for name in loaded if name.startswith(forbidden)]).is_empty()


LEGACY_PACKAGES = (
    "anthropics/document-skills",
    "anthropics/example-skills",
    "lgtm-hq/git-pr",
    "lgtm-hq/review",
)


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({}, LEGACY_PACKAGES),
        ({"skills": ["git-pr"]}, ("lgtm-hq/git-pr",)),
        (
            {"skills": ["review", "anthropics/example-skills"]},
            ("anthropics/example-skills", "lgtm-hq/review"),
        ),
        ({"bundle": "review"}, ("lgtm-hq/review",)),
        ({"vendor": "anthropics"}, LEGACY_PACKAGES[:2]),
        ({"skills": ["absent"]}, "Unknown plugin: absent"),
        ({"vendor": "absent"}, "Unknown vendor: absent"),
        ({"vendor": "anthropics", "skills": ["git-pr"]}, "plugin-atomic"),
        ({"bundle": "review", "skills": ["git-pr"]}, "not both"),
    ],
    ids=[
        "all",
        "skill",
        "skills",
        "bundle",
        "vendor",
        "bad-skill",
        "bad-vendor",
        "vendor-skill",
        "bundle-skill",
    ],
)
def test_legacy_selectors_map_to_packages(
    flags: dict[str, Any], expected: tuple[str, ...] | str
) -> None:
    """``--skill``/``--bundle``/``--vendor`` select package artifacts."""
    call: dict[str, Any] = {"skills": [], "bundle": None, "vendor": None} | flags
    if isinstance(expected, str):
        with pytest.raises(InstallError, match=expected):
            select_packages(packages=LEGACY_PACKAGES, **call)
    else:
        assert_that(select_packages(packages=LEGACY_PACKAGES, **call)).is_equal_to(
            expected
        )


def test_ambiguous_plugin_id_names_candidates() -> None:
    """A short plugin ID shared by two publishers needs its qualified form."""
    with pytest.raises(InstallError, match="x/tools, y/tools"):
        select_packages(
            packages=["x/tools", "y/tools"], skills=["tools"], bundle=None, vendor=None
        )
