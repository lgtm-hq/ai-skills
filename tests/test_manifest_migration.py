"""Lossless real-registry migration and deterministic production drift gate."""

from __future__ import annotations

import json
from collections.abc import Callable
from itertools import permutations
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from assertpy import assert_that

from ai_skills_engine import cli, package_sync
from ai_skills_engine.manifest.edit import patch_document
from ai_skills_engine.manifest.legacy import GENERATED_HEADER, render_legacy
from ai_skills_engine.manifest.load import load_manifest, read_document
from ai_skills_engine.registry.registry import load_registry, load_unique_yaml_text
from ai_skills_engine.vendors import manage

if TYPE_CHECKING:
    from manifest_helpers import VendorPinMatch

pytest_plugins = ("manifest_helpers",)

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
        capabilities={
            "teach": {
                "requires": [],
                "resources": [],
                "related": ["lgtm-hq/git-pr:skill/branch"],
            }
        },
    )
    data["vendors"][0]["include"] = ["mattpocock/mattpocock-skills"]
    data["vendors"][0]["exclude"] = []
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


@pytest.mark.parametrize("indent", [0, 2, 4, 6, 8])
def test_renovate_matches_manifest_and_regeneration(
    legacy_repo: Path,
    indent: int,
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
) -> None:
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
    path = legacy_repo / "ai-skills.yaml"
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    in_vendors = False
    for index, line in enumerate(lines):
        if line.startswith("vendors:"):
            in_vendors = True
        elif in_vendors and line.startswith(" "):
            lines[index] = " " * indent + line[2:]
        elif in_vendors and line.strip():
            in_vendors = False
    text = "".join(lines)
    assert_that(read_document(path)).is_equal_to(load_unique_yaml_text(text=text))
    matches = vendor_pin_matches(text)
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


@pytest.mark.parametrize("indent", [0, 2, 4, 6, 8])
@pytest.mark.parametrize("order", list(permutations(("id", "repo", "sha", "branch"))))
@pytest.mark.parametrize("comments", [False, True])
def test_renovate_extracts_reordered_vendor_records(
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
    indent: int,
    order: tuple[str, ...],
    comments: bool,
) -> None:
    """Recursive extraction merges fields per vendor across reordering and comments."""
    records = []
    expected = []
    for name, digest in (("first", "a" * 40), ("second", "b" * 40)):
        fields = {
            "id": name,
            "repo": f'"owner/{name}"',
            "sha": f"'{digest}'",
            "branch": "'release/next'",
        }
        lines = [f"{' ' * indent}- {order[0]}: {fields[order[0]]}\n"]
        for key in order[1:]:
            if comments:
                lines.extend(["\n", f"{' ' * (indent + 2)}# repo: ignored/comment\n"])
            lines.append(f"{' ' * (indent + 2)}{key}: {fields[key]} # tracked\n")
        records.append("".join(lines))
        expected.append(
            {
                "depName": f"owner/{name}",
                "currentDigest": digest,
                "currentValue": "release/next",
            }
        )
    text = "vendors: # declarations\n" + "".join(records) + "exports: []\n"
    # Both layouts are real YAML, not just strings accepted by the regex model.
    assert_that(load_unique_yaml_text(text=text)["vendors"]).is_length(2)
    matches = vendor_pin_matches(text)
    assert_that([match.groupdict() for match in matches]).is_equal_to(expected)
    for match in matches:
        start, end = match.span("currentDigest")
        assert_that(text[start:end]).is_equal_to(match["currentDigest"])


@pytest.mark.parametrize("indent", [0, 2, 4, 6, 8])
@pytest.mark.parametrize("missing", ["repo", "sha", "branch", "none"])
def test_renovate_never_borrows_fields_outside_vendor_record(
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
    indent: int,
    missing: str,
) -> None:
    """Nested mappings, adjacent vendors and later top-level sequences stay isolated."""
    pad = " " * (indent + 2)
    nested = pad + "  "
    fields = {"repo": "owner/first", "sha": "a" * 40, "branch": "main"}
    text = "vendors:\n" + " " * indent + "- id: first\n"
    text += (
        f"{pad}mapping:\n{nested}repo: ignored/mapping\n"
        f"{nested}sha: {'d' * 40}\n{nested}branch: hidden\n"
        f"{nested}packages:\n{nested}  - id: nested\n"
        f"{nested}    repo: ignored/nested\n"
        f"{nested}    sha: {'e' * 40}\n{nested}    branch: hidden\n"
    )
    text += "".join(
        f"{pad}{key}: {value}\n" for key, value in fields.items() if key != missing
    )
    text += (
        f"{' ' * indent}- id: second\n{pad}repo: owner/second\n"
        f"{pad}sha: {'b' * 40}\n{pad}branch: next\n"
        "x-other:\n- id: other\n  repo: ignored/top-level\n"
        f"  sha: {'c' * 40}\n  branch: hidden\n"
    )
    assert_that(load_unique_yaml_text(text=text)["vendors"]).is_length(2)
    expected = []
    if missing == "none":
        expected.append(
            {
                "depName": "owner/first",
                "currentDigest": "a" * 40,
                "currentValue": "main",
            }
        )
    expected.append(
        {"depName": "owner/second", "currentDigest": "b" * 40, "currentValue": "next"}
    )
    assert_that([match.groupdict() for match in vendor_pin_matches(text)]).is_equal_to(
        expected
    )


def test_renovate_ignores_mapping_templates_and_unrelated_repos(
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
) -> None:
    """Only vendor item headers declare dependencies, not incidental repo fields."""
    text = (
        "publisher:\n    repo: irrelevant/publisher\n"
        f"    sha: {'a' * 40}\n    branch: main\n"
        "vendors:\n  - id: real-vendor\n    repo: example/real\n"
        f"    sha: {'b' * 40}\n    branch: main # tracked\n"
        "    mapping:\n      repo: irrelevant/mapping\n"
        f"      sha: {'c' * 40}\n      branch: hidden\n"
        "x-template: |\n    repo: irrelevant/template\n"
        f"    sha: {'d' * 40}\n    branch: hidden\n"
        "x-unrelated:\n  - id: unrelated\n    repo: irrelevant/other\n"
        f"    sha: {'e' * 40}\n    branch: hidden\n"
    )
    matches = vendor_pin_matches(text)
    assert_that([match["depName"] for match in matches]).is_equal_to(["example/real"])


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
