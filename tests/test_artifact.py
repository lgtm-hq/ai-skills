"""End-to-end resolved artifact, structural rewrite and deterministic tar contracts."""

import io
import json
import os
import shutil
import tarfile
from dataclasses import replace
from pathlib import Path

import pytest
from artifact_helpers import FIXTURE, bake_fixture, index_at, tar_files
from assertpy import assert_that
from provenance_helpers import change_policy, vendor_roots

from ai_skills_engine.artifact import artifact_name, write_artifacts
from ai_skills_engine.artifacts.format import canonical_tar, digest, validate_index
from ai_skills_engine.artifacts.references import rewrite_fields, rewrite_markdown
from ai_skills_engine.inventory.load import load_inventory
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.registry.safe_tree import validate_internal_references
from ai_skills_engine.selection.load import load_inputs

pytest_plugins = ["artifact_helpers"]


def test_canonical_artifacts_and_golden(artifact_repo: Path, tmp_path: Path) -> None:
    """Actual builds ignore checkout path, mtime and nonidentity mode/umask bits."""
    first, second = tmp_path / "first", tmp_path / "second"
    result = bake_fixture(root=artifact_repo, destination=first)
    copied = tmp_path / "copied"
    shutil.copytree(src=artifact_repo, dst=copied)
    for path in copied.rglob("*"):
        if path.is_file():
            os.utime(path, (1234567890, 1234567890))
            path.chmod(0o700 if path.stat().st_mode & 0o100 else 0o600)
    original_umask = os.umask(0o077)
    try:
        other = bake_fixture(root=copied, destination=second)
    finally:
        os.umask(original_umask)
    assert_that(other).is_equal_to(result)
    expected = {path.name: path.read_bytes() for path in first.iterdir()}
    assert_that(
        {path.name: path.read_bytes() for path in second.iterdir()}
    ).is_equal_to(expected)
    assert_that(
        {path.name: path.read_bytes() for path in (FIXTURE / "golden").iterdir()}
    ).is_equal_to(expected)
    name = artifact_name("fixture/tools")
    assert_that(digest((first / name).read_bytes())).is_equal_to(
        result["packages"]["fixture/tools"]["artifactDigest"]
    )
    assert_that((first / (name + ".sha256")).read_text()).starts_with(
        result["packages"]["fixture/tools"]["artifactDigest"][7:]
    )
    with tarfile.open(fileobj=io.BytesIO(expected[name]), mode="r:") as archive:
        members = list(archive)
    assert_that([member.name for member in members]).is_sorted()
    for member in members:
        assert_that(
            (member.uid, member.gid, member.mtime, member.uname, member.gname)
        ).is_equal_to((0, 0, 0, "", ""))
        assert_that(member.mode).is_in(0o644, 0o755)
        assert_that(
            set(member.pax_headers).intersection({"atime", "ctime", "mtime"})
        ).is_empty()
    assert_that(
        tar_files(first / name)[
            "packages/fixture/tools/skill/start/_shared/fixture/shared/scripts/run.py"
        ][1]
    ).is_equal_to(0o755)


def test_closures_copies_links_and_lineage(artifact_repo: Path, tmp_path: Path) -> None:
    """One selected root pulls its cycle/resource closure and copies lineage twice."""
    output = tmp_path / "artifacts"
    bake_fixture(root=artifact_repo, destination=output)
    index = index_at(output)
    validate_index(index)
    caps = index["packages"][0]["capabilities"]
    ids = ["fixture/tools:skill/peer", "fixture/tools:skill/start"]
    inventory, selection = load_inputs(artifact_repo)
    assert_that(
        [item.id for item in selection.capabilities if item.state == "pulled-in"]
    ).is_equal_to([ids[0]])
    originals = {
        str(item.id): json.loads(item.lineage[0].to_json())
        for item in inventory.capabilities
    }
    files = tar_files(output / artifact_name("fixture/tools"))
    assert_that(json.loads(files["index.json"][0])["rootPackage"]).is_equal_to(
        "fixture/tools"
    )
    assert_that(json.dumps(index)).does_not_contain("artifactDigest")
    for cap in caps:
        assert_that(cap["closure"]).is_equal_to(
            {
                "capabilities": ids,
                "resources": ["fixture/tools:resource/shared"],
                "units": [ids],
            }
        )
        assert_that(cap["lineage"]).is_equal_to([originals[cap["id"]]])
        assert_that(cap["resources"][0]["lineage"]).is_equal_to(
            [json.loads(inventory.resources[0].lineage[0].to_json())]
        )
        exploded = tmp_path / cap["id"].rsplit("/", 1)[-1]
        for path, (data, _mode) in files.items():
            if path.startswith(cap["path"] + "/"):
                target = exploded / path.removeprefix(cap["path"] + "/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        validate_internal_references(root=exploded)
        assert_that(
            (exploded / "_shared/fixture/shared/scripts/run.py").read_bytes()
        ).is_equal_to((artifact_repo / "shared/scripts/run.py").read_bytes())
    start = next(cap for cap in caps if cap["id"].endswith("/start"))
    text = files[start["path"] + "/SKILL.md"][0].decode()
    assert_that(text).contains(
        "<_shared/fixture/shared/data/input.txt?mode=read#sample>",
        "`../../shared/data/input.txt`",
        '"Title stays unchanged"',
    )
    config = json.loads(files[start["path"] + "/config.json"][0])
    assert_that(config).is_equal_to(
        {
            "script": "_shared/fixture/shared/scripts/run.py",
            "prose": "../../shared/scripts/run.py stays unchanged",
        }
    )
    assert_that({item["mode"] for item in start["portability"]}).is_equal_to(
        {"user-explode", "repo-materialize"}
    )
    assert_that(caps[0]["portability"]).is_empty()


@pytest.mark.parametrize(
    "kind", ["format", "digest", "lineage", "missing-closure", "self-digest"]
)
def test_schema_rejects_incomplete_contract(
    artifact_repo: Path, tmp_path: Path, kind: str
) -> None:
    """Installed-resource schema requires the whole downstream contract."""
    output = tmp_path / "artifacts"
    bake_fixture(root=artifact_repo, destination=output)
    index = index_at(output)
    cap = index["packages"][0]["capabilities"][0]
    if kind == "format":
        index["artifactFormat"] = 2
    elif kind == "digest":
        cap["treeDigest"] = "invalid"
    elif kind == "lineage":
        cap["lineage"] = []
    elif kind == "self-digest":
        index["artifactDigest"] = "sha256:" + "a" * 64
    else:
        del cap["closure"]
    with pytest.raises(ValueError, match="Invalid artifact index"):
        validate_index(index)


def test_reexports_keep_full_shipped_legal_ancestry(
    provenance_repo: Path, tmp_path: Path
) -> None:
    """Every origin and intermediary is included, with unused imports omitted."""
    for publisher in ("x", "y", "z"):
        (provenance_repo / publisher / "LICENSE").write_text(
            f"License text from {publisher}.\n"
        )
    root = provenance_repo / "z"
    change_policy(root=root)
    output = tmp_path / "artifacts"
    roots = vendor_roots(provenance_repo)
    before = load_inventory(root, vendor_roots=roots, selection_candidates=True)
    bake_fixture(root=root, roots=roots, destination=output)
    records = {
        item["id"]: item
        for package in index_at(output)["packages"]
        for item in package["capabilities"]
    }
    for cap in before.capabilities:
        assert_that(records[str(cap.id)]["lineage"]).is_equal_to(
            [
                json.loads(chain.to_json())
                for chain in sorted(cap.lineage, key=lambda item: item.to_json())
            ]
        )
    files = tar_files(output / artifact_name("y/tools"))
    notices = files["NOTICE.md"][0].decode()
    assert_that(notices).contains("github.com/fixture/x", "github.com/fixture/y")
    assert_that(notices).does_not_contain("fixture/z")
    assert_that({path for path in files if path.startswith("LICENSES/")}).is_equal_to(
        {
            "LICENSES/github.com%2Ffixture%2Fx.txt",
            "LICENSES/github.com%2Ffixture%2Fy.txt",
        }
    )
    assert_that(
        b"License text from x." in b"".join(data for data, _ in files.values())
    ).is_true()


@pytest.mark.parametrize("control", ["deny", "exclude", "role"])
def test_invalid_selection_preserves_previous_generation(
    artifact_repo: Path, tmp_path: Path, control: str
) -> None:
    """Consumer vetoes on requirements fail before replacing any existing output."""
    output = tmp_path / "artifacts"
    bake_fixture(root=artifact_repo, destination=output)
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    path = artifact_repo / "ai-skills.yaml"
    document = read_document(path)
    if control == "deny":
        document["policy"]["deny"] = {"origins": ["github.com/fixture/artifacts"]}
        # Both roots are directly denied, yielding an empty valid artifact set.
        document["packages"][0]["exclude"] = ["fixture/tools:resource/shared"]
    elif control == "exclude":
        document["packages"][0]["exclude"] = ["fixture/tools:skill/peer"]
    else:
        document["packages"][0]["capabilities"][1]["resources"].append(
            "fixture/tools:resource/missing"
        )
    path.write_text(dump_document(document))
    if control == "deny":
        bake_fixture(root=artifact_repo, destination=output)
        assert_that(index_at(output)["packages"]).is_empty()
    else:
        with pytest.raises(ValueError, match="Artifact selection failed"):
            bake_fixture(root=artifact_repo, destination=output)
        assert_that(
            {path.name: path.read_bytes() for path in output.iterdir()}
        ).is_equal_to(before)


def test_changed_source_and_selection_mismatch_fail_before_publish(
    artifact_repo: Path, tmp_path: Path
) -> None:
    """A selected record cannot authorize changed payload bytes or stripped lineage."""
    inventory, selection = load_inputs(artifact_repo)
    output = tmp_path / "artifacts"
    altered = replace(
        selection,
        capabilities=tuple(
            replace(item, lineage=()) for item in selection.capabilities
        ),
    )
    with pytest.raises(ValueError, match="observations disagree"):
        write_artifacts(
            inventory=inventory,
            selection=altered,
            root=artifact_repo,
            vendor_roots={},
            destination=output,
        )
    (artifact_repo / "skills/start/SKILL.md").write_text("Changed since inventory.\n")
    with pytest.raises(ValueError, match="No authenticated source bytes"):
        write_artifacts(
            inventory=inventory,
            selection=selection,
            root=artifact_repo,
            vendor_roots={},
            destination=output,
        )
    assert_that(output.exists()).is_false()


@pytest.mark.parametrize(
    "text",
    [
        "[Text](../../shared/a.txt)",
        "[Text](<../../shared/a.txt>)",
        "![Image](../../shared/a.txt)",
        '[Unused]: ../../shared/a.txt "title"',
        '> [Unused]: ../../shared/a.txt "title"',
        "[Nested [label]](../../shared/a.txt)",
    ],
)
def test_structural_commonmark_destinations(text: str) -> None:
    """Use CommonMark roles to distinguish link destinations from similar bytes."""
    source = (
        text + "\n\n`../../shared/a.txt`\n\n```md\n[code](../../shared/a.txt)\n```\n"
    )
    changed = rewrite_markdown(
        text=source,
        replace=lambda value: (
            "_shared/a.txt" if value == "../../shared/a.txt" else None
        ),
    )
    assert_that(changed).contains(
        "<_shared/a.txt>", "`../../shared/a.txt`", "[code](../../shared/a.txt)"
    )
    assert_that(changed.count("<_shared/a.txt>")).is_equal_to(1)


@pytest.mark.parametrize("kind", ["json", "yaml", "frontmatter"])
def test_declared_structural_scalar_fields(kind: str) -> None:
    """Declared paths change while adjacent prose and code remain byte-identical."""
    source = (
        '{"path":"../../shared/file.txt", "prose":"../../shared/file.txt"}'
        if kind == "json"
        else 'path: "../../shared/file.txt"\nprose: "../../shared/file.txt"\n'
    )
    if kind == "frontmatter":
        source = "---\n" + source + "---\nCode ../../shared/file.txt stays.\n"
    changed = rewrite_fields(
        text=source,
        pointers=("/path",),
        markdown=kind == "frontmatter",
        replace=lambda _value: "_shared/file.txt",
    )
    assert_that(changed).contains('"_shared/file.txt"', '"../../shared/file.txt"')
    assert_that(changed.count('"_shared/file.txt"')).is_equal_to(1)


@pytest.mark.parametrize("path", ["../escape", "/absolute", "a/../escape", "a\\escape"])
def test_tar_paths_fail_closed(path: str) -> None:
    """Canonical writer never authorizes traversal or platform path ambiguity."""
    with pytest.raises(ValueError, match="Unsafe artifact entry"):
        canonical_tar({path: (b"fixture", 0o644)})


def test_resource_only_package_gets_its_own_artifact(
    artifact_repo: Path, tmp_path: Path
) -> None:
    """A pulled-in resource package is inventoried and independently transportable."""
    path = artifact_repo / "ai-skills.yaml"
    document = read_document(path)
    resources = document["packages"][0].pop("resources")
    document["packages"].append({"id": "resources", "resources": resources})
    for item in document["packages"][0]["capabilities"]:
        item["resources"] = ["fixture/resources:resource/shared"]
    path.write_text(dump_document(document))
    output = tmp_path / "artifacts"
    result = bake_fixture(root=artifact_repo, destination=output)
    assert_that(result["packages"]).contains_key("fixture/resources")
    index = index_at(output)
    package = next(
        item for item in index["packages"] if item["id"] == "fixture/resources"
    )
    assert_that(package["capabilities"]).is_empty()
    assert_that(package["resources"][0]["id"]).is_equal_to(
        "fixture/resources:resource/shared"
    )
    files = tar_files(output / artifact_name("fixture/resources"))
    assert_that(files).contains_key(
        "packages/fixture/resources/resource/shared/scripts/run.py"
    )
    assert_that(result["packages"]["fixture/resources"]["treeDigest"]).is_equal_to(
        package["treeDigest"]
    )


def test_generated_catalog_notice_omits_unused_vendor(
    artifact_repo: Path, tmp_path: Path
) -> None:
    """Known generated registry notices are rendered for the shipped origin set."""
    from ai_skills_engine.registry.registry import load_registry, render_notice

    vendor = {
        "id": "unused",
        "repo": "fixture/unused",
        "sha": "a" * 40,
        "license": "MIT",
        "homepage": "https://github.com/fixture/unused",
        "skillRoots": ["skills"],
    }
    registry = artifact_repo / "vendors.yaml"
    registry.write_text(dump_document({"vendors": [vendor]}))
    vendors = load_registry(registry_path=registry)
    (artifact_repo / "NOTICE.md").write_text(render_notice(vendors=vendors))
    output = tmp_path / "artifacts"
    bake_fixture(root=artifact_repo, destination=output)
    files = tar_files(output / artifact_name("fixture/tools"))
    assert_that(b"".join(data for data, _mode in files.values())).does_not_contain(
        b"fixture/unused"
    )
    assert_that([path for path in files if path.startswith("LICENSES/")]).is_length(1)


def test_artifact_build_never_executes_payload(
    artifact_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Executable fixture scripts are copied without process or hook execution."""
    import subprocess  # nosec B404 - execution APIs are patched to fail

    from ai_skills_engine.registry import safe_tree

    safe_tree._libc()

    def forbidden(*_args: object, **_kwargs: object) -> None:
        """Fail on any process execution within the artifact build boundary."""
        pytest.fail("Artifact build attempted payload execution")

    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    for name in dir(os):
        if name.startswith(("exec", "spawn", "posix_spawn")) or name in {
            "system",
            "popen",
        }:
            monkeypatch.setattr(os, name, forbidden)
    bake_fixture(root=artifact_repo, destination=tmp_path / "artifacts")


def test_late_validation_failure_keeps_complete_previous_generation(
    artifact_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure after staging metadata never publishes part of a generation."""
    output = tmp_path / "artifacts"
    bake_fixture(root=artifact_repo, destination=output)
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    original = validate_index
    calls = 0

    def fail_late(index: dict[str, object]) -> None:
        """Reject the tar-specific index after the catalog index succeeds."""
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("Synthetic late validation failure")
        original(index)

    monkeypatch.setattr("ai_skills_engine.artifacts.index.validate_index", fail_late)
    with pytest.raises(ValueError, match="late validation failure"):
        bake_fixture(root=artifact_repo, destination=output)
    assert_that(
        {path.name: path.read_bytes() for path in output.iterdir()}
    ).is_equal_to(before)


@pytest.mark.parametrize(
    "value", ["../missing.txt", "../../shared", "../../shared/scripts"]
)
def test_declared_directory_and_missing_path_portability(
    artifact_repo: Path, tmp_path: Path, value: str
) -> None:
    """Explicit path fields support resource directories and diagnose absent targets."""
    config = artifact_repo / "skills/start/config.json"
    config.write_text(json.dumps({"script": value}))
    output = tmp_path / "artifacts"
    bake_fixture(root=artifact_repo, destination=output)
    cap = next(
        item
        for item in index_at(output)["packages"][0]["capabilities"]
        if item["id"].endswith("/start")
    )
    files = tar_files(output / artifact_name("fixture/tools"))
    emitted = json.loads(files[cap["path"] + "/config.json"][0])
    if "missing" in value:
        assert_that(emitted["script"]).is_equal_to(value)
        assert_that([item["reason"] for item in cap["portability"]]).contains(
            "config.json: declared path is outside payload/required resources"
        )
    else:
        assert_that(emitted["script"]).starts_with("_shared/fixture/shared")
        assert_that([item["reason"] for item in cap["portability"]]).does_not_contain(
            "config.json: declared path is outside payload/required resources"
        )


def test_execution_surface_advice_uses_delivered_json(
    artifact_repo: Path, tmp_path: Path
) -> None:
    """Changed lifecycle commands recommend major through the actual build pipeline."""
    from ai_skills_engine.semver_advice import recommend_semver

    path = artifact_repo / "ai-skills.yaml"
    document = read_document(path)
    document["packages"][0]["capabilities"].append(
        {"id": "lifecycle", "role": "lifecycle", "path": "hooks.json"}
    )
    document["packages"][0]["include"].append("fixture/tools:lifecycle/lifecycle")
    path.write_text(dump_document(document))
    config = artifact_repo / "hooks.json"
    hooks = {
        "hooks": {
            "SessionStart": [
                {"hooks": [{"type": "command", "command": "fixture-command"}]}
            ]
        }
    }
    config.write_text(json.dumps(hooks))
    output = tmp_path / "artifacts"
    bake_fixture(root=artifact_repo, destination=output)
    before = index_at(output)
    hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"] = "changed-fixture-command"
    config.write_text(json.dumps(hooks))
    bake_fixture(root=artifact_repo, destination=output)
    after = index_at(output)
    cap = next(
        item
        for item in after["packages"][0]["capabilities"]
        if item["role"] == "lifecycle"
    )
    assert_that(cap["executionSurface"]).is_equal_to(hooks)
    advice = recommend_semver(before, after)
    assert_that(advice.level).is_equal_to("major")
    assert_that("\n".join(advice.reasons)).contains("Execution surface changed")


def test_legal_acknowledgements_bind_exact_consumer_owned_bytes(
    artifact_repo: Path, tmp_path: Path
) -> None:
    """Legal content retains the path/rule/digest acknowledgement boundary."""
    import hashlib

    secret = "AKIA" + "A" * 16
    legal = artifact_repo / "LICENSE"
    legal.write_text("Synthetic fixture documentation: " + secret + "\n")
    output = tmp_path / "artifacts"
    with pytest.raises(ValueError, match="aws-access-key-id") as error:
        bake_fixture(root=artifact_repo, destination=output)
    assert_that(str(error.value)).does_not_contain(secret)
    manifest = artifact_repo / "ai-skills.yaml"
    document = read_document(manifest)
    document["overrides"] = {
        "ingestAllow": [
            {
                "path": "LICENSE",
                "rule": "aws-access-key-id",
                "sha256": hashlib.sha256(legal.read_bytes()).hexdigest(),
                "reason": "Synthetic fixture documentation example.",
            }
        ]
    }
    manifest.write_text(dump_document(document))
    bake_fixture(root=artifact_repo, destination=output)
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    legal.write_text(legal.read_text() + "Changed fixture bytes.\n")
    with pytest.raises(ValueError, match="aws-access-key-id"):
        bake_fixture(root=artifact_repo, destination=output)
    assert_that(
        {path.name: path.read_bytes() for path in output.iterdir()}
    ).is_equal_to(before)


def test_legal_content_diff_recommends_patch(
    artifact_repo: Path, tmp_path: Path
) -> None:
    """A changed license body remains visible to advice through index digests."""
    from ai_skills_engine.semver_advice import recommend_semver

    output = tmp_path / "artifacts"
    bake_fixture(root=artifact_repo, destination=output)
    before = index_at(output)
    license_file = artifact_repo / "LICENSE"
    license_file.write_text(license_file.read_text() + "Additional fixture notice.\n")
    bake_fixture(root=artifact_repo, destination=output)
    advice = recommend_semver(before, index_at(output))
    assert_that(advice.level).is_equal_to("patch")
    assert_that(advice.reasons).contains("License or notice content changed")
