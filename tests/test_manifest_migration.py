"""Lossless real-registry migration and deterministic production drift gate."""

import json
import re
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli, package_sync
from ai_skills_engine.manifest.edit import patch_document
from ai_skills_engine.manifest.legacy import GENERATED_HEADER, render_legacy
from ai_skills_engine.manifest.load import load_manifest, read_document
from ai_skills_engine.registry.registry import load_registry
from ai_skills_engine.vendors import manage

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "manifest"


@pytest.fixture
def legacy_repo(tmp_path: Path) -> Path:
    """Copy immutable pre-migration registry bytes into a scratch author root.

    Args:
        tmp_path: Isolated output root.

    Returns:
        Unmigrated repository.
    """
    for name in ("bundles.yaml", "vendors.yaml"):
        (tmp_path / name).write_bytes((FIXTURES / "legacy" / name).read_bytes())
    return tmp_path


def test_real_migration_exact_roundtrip_and_cli_drift(legacy_repo: Path) -> None:
    """Migrate all real entries, retain mapping fields and reproduce exact bytes."""
    original = {
        name: (legacy_repo / name).read_bytes()
        for name in ("bundles.yaml", "vendors.yaml")
    }
    original_vendors = load_registry(registry_path=legacy_repo / "vendors.yaml")
    args = ["--repo-root", str(legacy_repo), "manifest"]
    assert_that(cli.main([*args, "migrate"])).is_zero()
    data = read_document(legacy_repo / "ai-skills.yaml")
    assert_that(data["packages"][-1]["id"]).is_equal_to("other")
    for old, new in zip(
        read_document(legacy_repo / "vendors.yaml")["vendors"],
        data["vendors"],
        strict=True,
    ):
        assert_that(new["mapping"]["packages"]).is_equal_to(old["plugins"])
        assert_that(new["mapping"]["skillRoots"]).is_equal_to(old["skillRoots"])
    assert_that(cli.main([*args, "legacy", "--check"])).is_equal_to(1)
    assert_that(cli.main([*args, "legacy"])).is_zero()
    for name, raw in original.items():
        assert_that((legacy_repo / name).read_bytes()).is_equal_to(
            GENERATED_HEADER.encode() + raw
        )
        assert_that((ROOT / name).read_bytes()).is_equal_to(
            GENERATED_HEADER.encode() + raw
        )
    assert_that(load_registry(registry_path=legacy_repo / "vendors.yaml")).is_equal_to(
        original_vendors
    )
    assert_that(cli.main([*args, "legacy", "--check"])).is_zero()
    before = render_legacy(legacy_repo)
    (legacy_repo / "vendors.yaml").write_text("# drift\n")
    assert_that(cli.main([*args, "legacy", "--check"])).is_equal_to(1)
    assert_that((legacy_repo / "vendors.yaml").read_text()).is_equal_to("# drift\n")
    assert_that(render_legacy(legacy_repo)).is_equal_to(before)
    assert_that(cli.main([*args, "migrate"])).is_equal_to(1)


def test_actual_pin_edit_keeps_every_mapping_field(legacy_repo: Path) -> None:
    """Production set_sha edits the source and regenerates all real vendor pins."""
    assert_that(
        cli.main(["--repo-root", str(legacy_repo), "manifest", "migrate"])
    ).is_zero()
    manifest = legacy_repo / "ai-skills.yaml"
    data = read_document(manifest)
    mapping = data["vendors"][0]["mapping"]
    mapping["packages"][0].update(
        extraSkills=["extras/bonus"],
        extraFiles=["NOTICE.md"],
        agents=["reviewer"],
        renameSkills={"teach": "teach-mapped"},
        capabilities={"teach": {"requires": ["lgtm-hq/git-pr:skill/branch"]}},
    )
    data["vendors"][0]["include"] = []
    data["vendors"][0]["exclude"] = ["mattpocock/mattpocock-skills:skill/skip"]
    manifest.write_text(patch_document(text=manifest.read_text(), data=data))
    assert_that(
        cli.main(["--repo-root", str(legacy_repo), "manifest", "legacy"])
    ).is_zero()
    before_mapping = read_document(manifest)["vendors"][0]
    original = {
        name: (legacy_repo / name).read_bytes()
        for name in ("bundles.yaml", "vendors.yaml")
    }
    for index, vendor in enumerate(data["vendors"]):
        sha = f"{index + 1:040x}"
        manage.set_sha(repo_root=legacy_repo, vendor_id=vendor["id"], sha=sha)
        current = read_document(manifest)
        assert_that(current["vendors"][index]["sha"]).is_equal_to(sha)
        assert_that(
            load_registry(registry_path=legacy_repo / "vendors.yaml")[index].sha
        ).is_equal_to(sha)
        assert_that(
            cli.main(["--repo-root", str(legacy_repo), "manifest", "legacy", "--check"])
        ).is_zero()
    after_mapping = read_document(manifest)["vendors"][0]
    assert_that(
        {key: value for key, value in after_mapping.items() if key != "sha"}
    ).is_equal_to({key: value for key, value in before_mapping.items() if key != "sha"})
    assert_that((legacy_repo / "bundles.yaml").read_bytes()).is_equal_to(
        original["bundles.yaml"]
    )
    before = manifest.read_bytes()
    with pytest.raises(ValueError):
        manage.set_sha(
            repo_root=legacy_repo, vendor_id=data["vendors"][0]["id"], sha="main"
        )
    assert_that(manifest.read_bytes()).is_equal_to(before)


def test_migrated_identity_survives_a_payload_move(legacy_repo: Path) -> None:
    """ADR 0011 identities stay fixed when a payload's directory changes."""
    assert_that(
        cli.main(["--repo-root", str(legacy_repo), "manifest", "migrate"])
    ).is_zero()
    path = legacy_repo / "ai-skills.yaml"
    before = load_manifest(path).packages[0].capabilities[0]
    data = read_document(path)
    data["packages"][0]["capabilities"][0]["path"] = "skills/new-directory"
    path.write_text(patch_document(text=path.read_text(), data=data))
    after = load_manifest(path).packages[0].capabilities[0]
    assert_that(after.id).is_equal_to(before.id)
    assert_that(after.path).is_not_equal_to(before.path)


def test_renovate_matches_manifest_and_regeneration(legacy_repo: Path) -> None:
    """The actual custom manager extracts and edits every authoritative pin."""
    assert_that(
        cli.main(["--repo-root", str(legacy_repo), "manifest", "migrate"])
    ).is_zero()
    manager = next(
        item
        for item in json.loads((ROOT / "renovate.json").read_text())["customManagers"]
        if item.get("datasourceTemplate") == "git-refs"
    )
    assert_that(manager["managerFilePatterns"]).is_equal_to([r"/^ai-skills\.yaml$/"])
    pattern = manager["matchStrings"][0].replace("(?<", "(?P<")
    path = legacy_repo / "ai-skills.yaml"
    text = path.read_text()
    matches = list(re.finditer(pattern, text))
    vendors = load_registry(registry_path=legacy_repo / "vendors.yaml")
    assert_that(
        [
            (item["depName"], item["currentDigest"], item["currentValue"])
            for item in matches
        ]
    ).is_equal_to([(vendor.repo, vendor.sha, vendor.branch) for vendor in vendors])
    for match in reversed(matches):
        start, end = match.span("currentDigest")
        text = text[:start] + "f" * 40 + text[end:]
    path.write_text(text)
    assert_that(
        cli.main(["--repo-root", str(legacy_repo), "manifest", "legacy"])
    ).is_zero()
    assert_that(
        {
            vendor.sha
            for vendor in load_registry(registry_path=legacy_repo / "vendors.yaml")
        }
    ).is_equal_to({"f" * 40})


@pytest.mark.parametrize(
    "destination", ["npm/ai-skills/data/schema", "src/ai_skills_engine/manifest"]
)
def test_package_sync_copies_published_schema(destination: str) -> None:
    """The production renderer derives both package resources from one schema."""
    generated = package_sync.rendered_files("0.0.0-dev", repo_root=ROOT)
    path = ROOT / destination / "ai-skills.v1.schema.json"
    assert_that(generated[path]).is_equal_to(
        (ROOT / "schemas/ai-skills.v1.schema.json").read_text()
    )


@pytest.mark.parametrize(
    "destination", ["npm/ai-skills/data/schema", "src/ai_skills_engine/manifest"]
)
def test_schema_generator_and_drift_gate(tmp_path: Path, destination: str) -> None:
    """The real sync command detects stale schema copies and repairs them."""
    for relative in (
        "bundles.yaml",
        "vendors.yaml",
        "NOTICE.md",
        "npm/ai-skills/package.json",
        "schemas/ai-skills.v1.schema.json",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    args = ["--repo-root", str(tmp_path)]
    assert_that(package_sync.main(args)).is_zero()
    assert_that(package_sync.main([*args, "--check"])).is_zero()
    path = tmp_path / destination / "ai-skills.v1.schema.json"
    canonical = (tmp_path / "schemas/ai-skills.v1.schema.json").read_bytes()
    path.write_bytes(b"stale\n")
    assert_that(package_sync.main([*args, "--check"])).is_equal_to(1)
    assert_that(path.read_bytes()).is_equal_to(b"stale\n")
    assert_that(package_sync.main(args)).is_zero()
    assert_that(path.read_bytes()).is_equal_to(canonical)
    assert_that(package_sync.main([*args, "--check"])).is_zero()
