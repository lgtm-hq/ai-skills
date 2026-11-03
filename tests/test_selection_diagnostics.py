"""Reachable edge-diagnostic scope and persisted collision migration regressions."""

from pathlib import Path

import pytest
from assertpy import assert_that
from selection_helpers import collision_migration_case, edge_diagnostic_case
from test_selection_revision import run_plan

from ai_skills_engine.inventory.load import load_inventory

pytest_plugins = ["inventory_helpers"]


@pytest.mark.parametrize("source", ["local", "mapped", "manifest"])
@pytest.mark.parametrize(
    "edge",
    [
        "requires-rejected",
        "requires-missing",
        "resources-rejected",
        "resources-missing",
        "nonimported",
    ],
)
@pytest.mark.parametrize(
    "control", ["excluded", "narrow", "kept", "required", "transitive", "stale"]
)
def test_edge_diagnostics_follow_retained_requirers(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    source: str,
    edge: str,
    control: str,
) -> None:
    """Only known nonretained requirers lose edge errors; inventory stays strict."""
    root, vendor = inventory_repo
    requirer, target, chain = edge_diagnostic_case(
        root=root, vendor=vendor, source=source, edge=edge, control=control
    )
    field = "resources" if edge.startswith("resources") else "requires"
    code = (
        "inventory.non-imported-requires"
        if edge == "nonimported"
        else f"inventory.unknown-{field}"
    )
    inventory = load_inventory(
        root, vendor_roots={"vendor": vendor}, selection_candidates=True
    )
    finding = next(item for item in inventory.diagnostics if item.code == code)
    assert_that(finding.location).is_equal_to(requirer)
    assert_that(finding.warning).is_false()
    expected = 0 if control in {"excluded", "narrow"} else 1
    output = run_plan(root=root, vendor=vendor, capsys=capsys, expected=expected)
    findings = output["diagnostics"]
    codes = [item["code"] for item in findings]
    if expected == 0:
        assert_that(codes).does_not_contain(code)
    elif control == "stale":
        assert_that(codes).contains("selection.selector-unmatched", code)
    else:
        assert_that(codes).contains(code)
        required = next(
            item
            for item in findings
            if item["location"] == target
            and item["code"].startswith("selection.required-")
        )
        assert_that(required["chain"]).is_equal_to(list(chain))
        assert_that(required["fix"]).is_not_empty()
        if edge.endswith("rejected") and control != "required":
            assert_that(required["code"]).is_equal_to("selection.required-excluded")
        else:
            assert_that(required["code"]).is_equal_to("selection.required-missing")


@pytest.mark.parametrize("kind", ["capability", "package"])
@pytest.mark.parametrize("action", ["rename", "skip"])
@pytest.mark.parametrize(
    "control", ["migrated", "current", "stale", "malformed", "cycle", "duplicate"]
)
def test_collision_decisions_follow_explicit_migrations(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    kind: str,
    action: str,
    control: str,
) -> None:
    """Persistent decisions migrate exactly once, with duplicates checked afterward."""
    root, vendor = inventory_repo
    identity = collision_migration_case(
        root=root, control=control, action=action, kind=kind
    )
    expected = 0 if control in {"migrated", "current"} else 1
    output = run_plan(root=root, vendor=vendor, capsys=capsys, expected=expected)
    codes = [item["code"] for item in output["diagnostics"]]
    if expected == 0:
        entry = next(item for item in output["capabilities"] if item["id"] == identity)
        if action == "rename":
            assert_that(entry["names"]).is_equal_to(["renamed"])
            assert_that(entry["state"]).is_equal_to("selected")
        else:
            assert_that(entry["state"]).is_equal_to("excluded")
        assert_that(codes).does_not_contain("selection.namespace-collision")
    elif control == "malformed":
        assert_that(codes).contains(
            "invalid-id", "selection.invalid-collision-override"
        )
    else:
        assert_that(codes).contains("selection.invalid-collision-override")
        if control == "duplicate":
            duplicates = [
                item
                for item in output["diagnostics"]
                if item["code"] == "selection.invalid-collision-override"
            ]
            assert_that(duplicates).is_length(1)
            assert_that(duplicates[0]["location"]).is_equal_to(identity)
            assert_that(duplicates[0]["message"]).contains("duplicated")
