"""Fixture-backed production inventory loading, IDs, hashing and CLI behavior."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.inventory import load_inventory
from ai_skills_engine.inventory.capability_id import CapabilityId
from ai_skills_engine.inventory.package_id import PackageId
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document

pytest_plugins = ["inventory_helpers"]

ROOT = Path(__file__).resolve().parents[1]


def test_fixture_inventory_ids_roles_edges_and_aliases(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Real source entrypoint recognizes all roles and only declared edges."""
    root, vendor = inventory_repo
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([item for item in result.diagnostics if not item.warning]).is_empty()
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.vendor-pin-unverified"
    )
    records = {str(item.id): item for item in result.capabilities}
    assert_that(records).is_length(8)
    assert_that({item.role.value for item in records.values()}).is_equal_to(
        {"skill", "instruction", "specialist", "workflow", "lifecycle", "integration"}
    )
    start = records["fixture/tools:skill/stable"]
    helper = records["vendor/tools:skill/helper"]
    reviewer = records["vendor/tools:specialist/reviewer"]
    assert_that(str(start.package)).is_equal_to("fixture/tools")
    assert_that(start.origin).is_equal_to("github.com/fixture/catalog")
    assert_that(helper.origin).is_equal_to("github.com/upstream/tools")
    assert_that(helper.aliases).is_equal_to(("help-alias",))
    assert_that(str(reviewer.dialect)).is_equal_to("claude-code-agent")
    assert_that(str(helper.dialect)).is_equal_to("agent-skills")
    assert_that([str(item) for item in start.requires]).is_equal_to([str(helper.id)])
    assert_that([str(item) for item in start.related]).is_equal_to(
        ["fixture/tools:workflow/procedure"]
    )
    assert_that([str(item) for item in start.resources]).is_equal_to(
        ["fixture/tools:resource/guide"]
    )
    assert_that(helper.requires).is_empty()
    assert_that([str(item.path) for item in helper.payload]).is_equal_to(
        ["SKILL.md", "danger.py"]
    )
    assert_that({str(item.id) for item in result.resources}).is_equal_to(
        {"fixture/tools:resource/guide", "vendor/tools:resource/notice"}
    )
    assert_that(list(root.rglob("MUST-NOT-EXECUTE"))).is_empty()
    assert_that(list(vendor.rglob("MUST-NOT-EXECUTE"))).is_empty()
    with pytest.raises(FrozenInstanceError):
        start.origin = "changed"


def test_production_cli_json_is_byte_deterministic(
    inventory_repo: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Repeated JSON is sorted, stable and contains diagnostics without banners."""
    root, vendor = inventory_repo
    args = [
        "--repo-root",
        str(root),
        "inventory",
        "--json",
        "--vendor-root",
        f"vendor={vendor}",
    ]
    assert_that(cli.main(args)).is_zero()
    first = capsys.readouterr().out
    assert_that(cli.main(args)).is_zero()
    second = capsys.readouterr().out
    assert_that(second).is_equal_to(first)
    document = json.loads(first)
    ids = [item["id"] for item in document["capabilities"]]
    assert_that(ids).is_equal_to(sorted(ids))
    assert_that(first).does_not_contain(str(root), str(vendor))
    assert_that(
        cli.main(
            ["inventory", "--repo-root", str(root), "--vendor-root", f"vendor={vendor}"]
        )
    ).is_zero()
    assert_that(capsys.readouterr().out).contains(
        "fixture/tools:skill/stable", "inventory.host-specific-frontmatter"
    )
    assert_that(
        cli.main(
            [
                "manifest",
                "validate",
                "--repo-root",
                str(root),
                "--vendor-root",
                f"vendor={vendor}",
            ]
        )
    ).is_zero()
    assert_that(capsys.readouterr().out).contains(
        "inventory.unknown-frontmatter", "codex=unverified", "cursor=unverified"
    )


def test_identity_survives_path_and_byte_changes(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Declared ID survives moving, display renaming, mode and content changes."""
    root, vendor = inventory_repo
    before = load_inventory(root, vendor_roots={"vendor": vendor})
    original = next(item for item in before.capabilities if item.id.name == "stable")
    (root / "skills/start").rename(root / "skills/moved")
    document = read_document(root / "ai-skills.yaml")
    document["packages"][0]["capabilities"][0]["path"] = "skills/moved"
    (root / "ai-skills.yaml").write_text(dump_document(document))
    entry = root / "skills/moved/SKILL.md"
    entry.write_text(
        entry.read_text().replace("name: start", "name: another-display-name")
    )
    entry.chmod(0o755)
    after = load_inventory(root, vendor_roots={"vendor": vendor})
    moved = next(item for item in after.capabilities if item.id.name == "stable")
    assert_that(moved.id).is_equal_to(original.id)
    assert_that(moved.tree_digest).is_not_equal_to(original.tree_digest)
    assert_that(moved.payload[0].mode).is_equal_to(0o755)
    digest = moved.tree_digest
    entry.chmod(0o644)
    changed_mode = next(
        item
        for item in load_inventory(root, vendor_roots={"vendor": vendor}).capabilities
        if item.id == moved.id
    )
    assert_that(changed_mode.tree_digest).is_not_equal_to(digest)


@pytest.mark.parametrize(
    "kind,value",
    [
        (PackageId, "fixture/tools"),
        (CapabilityId, "fixture/tools:workflow/run"),
        (ResourceId, "fixture/tools:resource/notice"),
    ],
)
def test_identity_parse_render(kind: type, value: str) -> None:
    """Typed IDs roundtrip exact qualified identities."""
    assert_that(str(kind.parse(value))).is_equal_to(value)


@pytest.mark.parametrize(
    "kind,value",
    [
        (PackageId, "fixture/tools:skill/run"),
        (CapabilityId, "fixture/tools"),
        (CapabilityId, "fixture/tools:resource/a"),
        (CapabilityId, "fixture/tools:skill/*"),
        (ResourceId, "fixture/tools:skill/a"),
        (ResourceId, "fixture/tools:resource/../a"),
    ],
)
def test_identity_rejects_wrong_kind_and_selectors(kind: type, value: str) -> None:
    """IDs cannot silently accept paths, selectors or another record kind."""
    with pytest.raises(ValueError):
        kind.parse(value)


def test_six_actual_first_party_invocation_restrictions() -> None:
    """Canonical source inventory reports every real restricted first-party skill."""
    result = load_inventory(ROOT)
    restricted = [
        item
        for item in result.diagnostics
        if item.code == "inventory.host-specific-frontmatter"
        and "disable-model-invocation" in item.message
    ]
    assert_that({item.location.rsplit("/", 1)[1] for item in restricted}).is_equal_to(
        {
            "audit-merges",
            "babysit-pr",
            "backlog",
            "implement-issues",
            "jira",
            "sweep-prs",
        }
    )
    assert_that(restricted).is_length(6)
    assert_that(
        all(
            item.warning
            and "claude-code=preserve" in item.message
            and "codex=unverified" in item.message
            and "cursor=unverified" in item.message
            for item in restricted
        )
    ).is_true()
    # Contract, not a catalog census: every declared local capability is inventoried.
    declared = sum(
        len(package.get("capabilities", []))
        for package in read_document(ROOT / "ai-skills.yaml")["packages"]
    )
    assert_that(declared).is_positive()
    assert_that(result.capabilities).is_length(declared)
