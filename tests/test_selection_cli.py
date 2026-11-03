"""Real offline plan resolution, drift/schema failures and write-free controls."""

import json
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.legacy import legacy_documents
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.validate import validate_document
from ai_skills_engine.selection.load import load_selection

pytest_plugins = ["inventory_helpers"]


def _write(root: Path, document: dict) -> None:
    """Update only a fixture manifest.

    Args:
        root: Isolated fixture repository.
        document: Manifest input.
    """
    (root / "ai-skills.yaml").write_text(dump_document(document))


@pytest.mark.parametrize("include", [None, [], ["fixture/tools:skill/stable"]])
def test_real_plan_local_include_and_vendor_closure(
    inventory_repo: tuple[Path, Path], include: list[str] | None
) -> None:
    """Narrow roots still bring vendor requirements/resources from full candidates."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    if include is not None:
        document["packages"][0]["include"] = include
    document["vendors"][0]["include"] = []
    _write(root, document)
    result = load_selection(root, vendor_roots={"vendor": vendor})
    assert_that(result.valid).is_true()
    kept = {
        item.id
        for item in result.capabilities
        if item.state in {"selected", "pulled-in"}
    }
    if include == []:
        assert_that(kept).is_empty()
    else:
        assert_that(kept).contains(
            "fixture/tools:skill/stable", "vendor/tools:skill/helper"
        )
        assert_that(
            {item.id for item in result.resources if item.state == "pulled-in"}
        ).is_equal_to({"fixture/tools:resource/guide", "vendor/tools:resource/notice"})


def test_plan_sees_vendor_exclusion_before_edge_resolution(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Candidate loading differentiates a consumer veto from missing inventory."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    document["packages"][0]["include"] = ["fixture/tools:skill/stable"]
    document["vendors"][0]["include"] = []
    document["vendors"][0]["exclude"] = ["vendor/tools:skill/helper"]
    _write(root, document)
    result = load_selection(root, vendor_roots={"vendor": vendor})
    finding = next(
        item
        for item in result.diagnostics
        if item.code == "selection.required-excluded"
    )
    assert_that(finding.chain).is_equal_to(
        ("fixture/tools:skill/stable", "vendor/tools:skill/helper")
    )
    assert_that([item.code for item in result.diagnostics]).does_not_contain(
        "inventory.unknown-requires"
    )


@pytest.mark.parametrize("omit", ["extraFiles", "resources"])
def test_hard_case_vendor_mapping_truncated_resource_ingest_fails(
    inventory_repo: tuple[Path, Path], omit: str
) -> None:
    """Missing ingest and missing resource grants retain the fail-closed link check."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    package = document["vendors"][0]["mapping"]["packages"][0]
    if omit == "extraFiles":
        package["extraFiles"] = []
    else:
        package["capabilities"]["help"]["resources"] = []
    _write(root, document)
    result = load_selection(root, vendor_roots={"vendor": vendor})
    assert_that(result.valid).is_false()
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.undeclared-resource"
    )


@pytest.mark.parametrize("field", ["include", "exclude"])
def test_path_selector_is_manifest_error_before_plan(
    inventory_repo: tuple[Path, Path], field: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file operand cannot weaken whole-capability selection or write outputs."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    document["packages"][0][field] = ["skills/start/SKILL.md"]
    assert_that([item.code for item in validate_document(document)]).contains(
        "invalid-selector"
    )
    _write(root, document)
    assert_that(
        cli.main(
            [
                "plan",
                "--json",
                "--repo-root",
                str(root),
                "--vendor-root",
                f"vendor={vendor}",
            ]
        )
    ).is_equal_to(1)
    output = json.loads(capsys.readouterr().out)
    assert_that([item["code"] for item in output["diagnostics"]]).contains(
        "invalid-selector"
    )
    assert_that(list(root.glob("*.lock"))).is_empty()


def test_selector_drift_leaves_lock_generation_and_inputs_unchanged(
    inventory_repo: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Rename misses fail the real CLI; only an explicit migration keeps validity."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    document["packages"][0]["include"] = ["fixture/tools:skill/old-id"]
    _write(root, document)
    (root / "ai-skills.lock").write_bytes(b"old lock\n")
    (root / "installed-generation").write_bytes(b"old generation\n")
    before = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    args = [
        "plan",
        "--json",
        "--repo-root",
        str(root),
        "--vendor-root",
        f"vendor={vendor}",
    ]
    assert_that(cli.main(args)).is_equal_to(1)
    assert_that(capsys.readouterr().out).contains("selection.selector-unmatched")
    after = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert_that(after).is_equal_to(before)
    document["overrides"] = {
        "migrations": [
            {"from": "fixture/tools:skill/old-id", "to": "fixture/tools:skill/stable"}
        ]
    }
    _write(root, document)
    assert_that(cli.main(args)).is_zero()
    output = json.loads(capsys.readouterr().out)
    assert_that(
        next(
            item
            for item in output["capabilities"]
            if item["id"] == "fixture/tools:skill/stable"
        )["state"]
    ).is_equal_to("selected")
    assert_that((root / "ai-skills.lock").read_bytes()).is_equal_to(b"old lock\n")
    assert_that((root / "installed-generation").read_bytes()).is_equal_to(
        b"old generation\n"
    )


def test_real_plan_text_json_determinism_and_offline_execution(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan has no acquisition or vendor-execution surface and lists all records."""
    root, vendor = inventory_repo

    def forbidden(*args: object, **kwargs: object) -> None:
        """Reject any subprocess execution during the pure plan command."""
        pytest.fail("plan must not execute vendor code or acquire inputs")

    monkeypatch.setattr("subprocess.run", forbidden)
    args = ["--repo-root", str(root), "plan", "--vendor-root", f"vendor={vendor}"]
    assert_that(cli.main([*args, "--json"])).is_zero()
    first = capsys.readouterr().out
    assert_that(cli.main([*args, "--json"])).is_zero()
    assert_that(capsys.readouterr().out).is_equal_to(first)
    data = json.loads(first)
    assert_that(data["capabilities"]).is_length(8)
    assert_that(data["resources"]).is_length(2)
    for entry in [*data["capabilities"], *data["resources"]]:
        assert_that(entry["reason"]).is_not_empty()
        assert_that(entry["state"]).is_in(
            "selected", "pulled-in", "excluded", "denied", "unsupported"
        )
    assert_that(cli.main(args)).is_zero()
    assert_that(capsys.readouterr().out).contains(
        "namespace", "selected", "resource/guide"
    )
    assert_that(list(vendor.rglob("MUST-NOT-EXECUTE"))).is_empty()


@pytest.mark.parametrize("selector", [[], ["fixture/tools:skill/stable"]])
def test_local_selection_remains_fail_closed_for_legacy_publication(
    selector: list[str],
) -> None:
    """Legacy writers cannot discard a newly supported local narrowing declaration."""
    data = {
        "apiVersion": "ai-skills.dev/v1",
        "publisher": {"id": "fixture"},
        "packages": [{"id": "tools", "include": selector, "capabilities": []}],
        "exports": ["tools"],
    }
    with pytest.raises(ValueError, match="manifest-aware publication"):
        legacy_documents(data)


def test_vendor_own_migration_preserves_selectors_and_requirements(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Publisher-local migration metadata cannot import vendor policy authority."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    document["vendors"][0].pop("mapping")
    document["vendors"][0]["include"] = ["actual/tools:skill/old-id"]
    document["exports"] = ["tools"]
    document["packages"][0]["include"] = ["fixture/tools:skill/stable"]
    document["packages"][0]["capabilities"][0]["requires"] = [
        "actual/tools:skill/old-id"
    ]
    _write(root, document)
    _write(
        vendor,
        {
            "apiVersion": "ai-skills.dev/v1",
            "publisher": {"id": "actual"},
            "packages": [
                {
                    "id": "tools",
                    "capabilities": [{"id": "new-id", "path": "skills/help"}],
                }
            ],
            "overrides": {
                "migrations": [
                    {
                        "from": "actual/tools:skill/old-id",
                        "to": "actual/tools:skill/new-id",
                    }
                ]
            },
            "policy": {"deny": {"origins": ["github.com/fixture/catalog"]}},
        },
    )
    (vendor / "skills/help/SKILL.md").write_text(
        "---\nname: help\ndescription: Helper.\n---\n"
    )
    result = load_selection(root, vendor_roots={"vendor": vendor})
    assert_that(result.valid).is_true()
    kept = {
        entry.id
        for entry in result.capabilities
        if entry.state in {"selected", "pulled-in"}
    }
    assert_that(kept).contains(
        "fixture/tools:skill/stable", "actual/tools:skill/new-id"
    )
    assert_that([item.code for item in result.diagnostics]).contains(
        "vendor-authority-ignored"
    )


@pytest.mark.parametrize("role", ["integration", "lifecycle", "skill"])
def test_source_destination_name_collisions_across_distinct_stable_ids(
    inventory_repo: tuple[Path, Path],
    role: str,
) -> None:
    """Configuration keys and source names must collide even when IDs differ."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    package = document["packages"][0]
    original = next(
        item for item in package["capabilities"] if item.get("role", "skill") == role
    )
    package["capabilities"].append({**original, "id": "distinct-id"})
    _write(root, document)
    result = load_selection(root, vendor_roots={"vendor": vendor})
    collision = next(
        item
        for item in result.diagnostics
        if item.code == "selection.namespace-collision"
    )
    assert_that(collision.message).contains("distinct-id", original["id"])
    assert_that(result.valid).is_false()


def test_missing_offline_vendor_cannot_produce_a_valid_partial_plan(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Default import roots require a complete locally supplied pinned inventory."""
    root, _ = inventory_repo
    result = load_selection(root)
    assert_that(result.valid).is_false()
    assert_that([item.code for item in result.diagnostics]).contains(
        "selection.vendor-unavailable", "inventory.vendor-unavailable"
    )
    finding = next(
        item
        for item in result.diagnostics
        if item.code == "selection.vendor-unavailable"
    )
    assert_that(finding.fix).contains("--vendor-root vendor=PATH")
