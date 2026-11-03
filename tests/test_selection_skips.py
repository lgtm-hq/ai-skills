"""Persisted skips survive rejected payloads without authorizing unknown IDs."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that
from inventory_helpers import inventory_snapshot
from selection_helpers import PREFIX, inventory_graph
from test_selection_migrations import live_migration_case
from test_selection_revision import run_plan

from ai_skills_engine import cli
from ai_skills_engine.inventory.capability_id import CapabilityId
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.manifest.collision import Collision
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.overrides import Overrides
from ai_skills_engine.selection.rules import select

pytest_plugins = ["inventory_helpers"]

SKIP_CONTROLS = (
    "live-skip",
    "rejected-skip",
    "live-rename",
    "rejected-rename",
    "missing-skip",
    "missing-rename",
    "resource-skip",
    "resource-rename",
    "duplicate",
    "migrated",
    "converged",
    "required",
    "stale-selector",
)


def rejected_collision_case(
    *, root: Path, vendor: Path, source: str, control: str
) -> tuple[str, int]:
    """Prepare real payload failures and persisted decisions for public CLI tests.

    Args:
        root: Isolated consumer inputs.
        vendor: Offline vendor snapshot.
        source: Local, mapped or manifest-bearing capability declaration.
        control: Decision, identity or retained-requirement control.

    Returns:
        Declared capability identity and required plan exit status.
    """
    if source == "manifest":
        target, _ = live_migration_case(
            root=root,
            vendor=vendor,
            author="consumer",
            kind="capability",
            control="baseline",
        )
    document = read_document(root / "ai-skills.yaml")
    package = document["packages"][0]
    package["include"] = []
    package["capabilities"][0]["requires"] = []
    imported = document["vendors"][0]
    imported.pop("exclude", None)
    if source == "local":
        package.pop("include")
        target = "fixture/tools:skill/stable"
        payload = root / "skills/start/SKILL.md"
    else:
        target = "vendor/tools:skill/helper"
        payload = (
            vendor / f"skills/{'helper' if source == 'manifest' else 'help'}/SKILL.md"
        )
    action = "rename" if control.endswith("rename") else "skip"
    decision = target
    if control.startswith("missing"):
        decision = "vendor/tools:skill/absent"
    elif control.startswith("resource"):
        decision = "fixture/tools:resource/guide"
    if not control.startswith("live"):
        if source == "mapped":
            # Discovery still sees the mapped directory; loading rejects its body.
            payload.write_text("---\nname: help\n---\nMissing description.\n")
        else:
            payload.unlink()
    override: dict[str, Any] = {
        "capability": decision,
        "action": action,
        **({"name": "consumer-name"} if action == "rename" else {}),
    }
    collisions = [override]
    document["overrides"] = {"collisions": collisions}
    if control in {"migrated", "converged"}:
        old = target.rsplit("/", 1)[0] + "/old"
        # A later migration must not dislodge the observed rejected target.
        onward = target.rsplit("/", 1)[0] + "/absent"
        document["overrides"]["migrations"] = [
            {"from": old, "to": target},
            {"from": target, "to": onward},
        ]
        override["capability"] = old
        if control == "converged":
            collisions.append({"capability": target, "action": "skip"})
    elif control == "duplicate":
        collisions.append(dict(override))
    elif control == "required":
        # Two roots reach the target; BFS must retain the direct shortest witness.
        package["include"] = ["fixture/tools:workflow/procedure"]
        package["capabilities"][3]["requires"] = [target]
        package["capabilities"][2]["requires"] = ["fixture/tools:workflow/procedure"]
        package["include"].append("fixture/tools:specialist/specialist")
        if source != "local":
            imported["include"] = []
    elif control == "stale-selector":
        package["exclude"] = ["fixture/tools:skill/absent"]
    (root / "ai-skills.yaml").write_text(dump_document(document))
    (root / "ai-skills.lock").write_bytes(b"unchanged lock\n")
    (root / "installed-generation").write_bytes(b"unchanged generation\n")
    for path in (root / "ai-skills.yaml", vendor / "NOTICE.md"):
        path.chmod(0o640)
    expected = int(
        control not in {"live-skip", "rejected-skip", "live-rename", "migrated"}
    )
    return target, expected


def check_rejected_collision_plan(
    *, output: dict[str, Any], target: str, control: str
) -> None:
    """Check public identity, veto and failure contracts shared with wheel tests.

    Args:
        output: Actual CLI JSON result.
        target: Declared target, including when its payload was rejected.
        control: Fixture decision and failure control.
    """
    entries = {item["id"]: item for item in output["capabilities"]}
    codes = [item["code"] for item in output["diagnostics"]]
    valid_skip = control in {
        "live-skip",
        "rejected-skip",
        "migrated",
        "required",
        "stale-selector",
        "duplicate",
        "converged",
    }
    if valid_skip:
        assert_that(entries[target]["state"]).is_equal_to("excluded")
        assert_that(entries[target]["reason"]).is_equal_to("overrides.collisions: skip")
        assert_that(codes).does_not_contain(
            "selection.required-missing", "inventory.invalid-payload"
        )
    if control in {"duplicate", "converged"}:
        findings = [
            item
            for item in output["diagnostics"]
            if item["code"] == "selection.invalid-collision-override"
        ]
        assert_that(findings).is_length(1)
        assert_that(findings[0]["location"]).is_equal_to(target)
        assert_that(findings[0]["message"]).contains("duplicated")
    elif control == "required":
        finding = next(
            item
            for item in output["diagnostics"]
            if item["code"] == "selection.required-excluded"
        )
        assert_that(finding["chain"]).is_equal_to(
            ["fixture/tools:workflow/procedure", target]
        )
        assert_that(finding["fix"]).is_not_empty()
    elif control == "stale-selector":
        assert_that(codes).contains("selection.selector-unmatched")
    elif control == "live-rename":
        assert_that(entries[target]["names"]).is_equal_to(["consumer-name"])
    elif control == "rejected-rename" or control.startswith(("missing", "resource")):
        assert_that(codes).contains("selection.invalid-collision-override")
        assert_that(entries[target]["names"]).does_not_contain("consumer-name")
    if control in {
        "live-skip",
        "rejected-skip",
        "migrated",
        "required",
        "stale-selector",
    }:
        assert_that(codes).does_not_contain("selection.invalid-collision-override")


@pytest.mark.parametrize("source", ["local", "mapped", "manifest"])
@pytest.mark.parametrize("control", SKIP_CONTROLS)
def test_actual_plan_rejected_collision_decisions(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    control: str,
) -> None:
    """Actual CLI replays skips with immutable inputs and strict inventory errors."""
    root, vendor = inventory_repo
    target, expected = rejected_collision_case(
        root=root, vendor=vendor, source=source, control=control
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        """Forbid vendor execution while allowing the real in-process CLI."""
        pytest.fail("planning must not execute vendor code")

    monkeypatch.setattr("subprocess.run", forbidden)
    before = inventory_snapshot(root, vendor)
    if not control.startswith("live"):
        assert_that(
            cli.main(
                [
                    "inventory",
                    "--json",
                    "--repo-root",
                    str(root),
                    "--vendor-root",
                    f"vendor={vendor}",
                ]
            )
        ).is_equal_to(1)
        inventory = json.loads(capsys.readouterr().out)
        assert_that([item["code"] for item in inventory["diagnostics"]]).contains(
            "inventory.unknown-requires"
            if control == "required" and source != "local"
            else "inventory.invalid-payload"
        )
    output = run_plan(root=root, vendor=vendor, capsys=capsys, expected=expected)
    check_rejected_collision_plan(output=output, target=target, control=control)
    assert_that(inventory_snapshot(root, vendor)).is_equal_to(before)


@pytest.mark.parametrize(
    "control",
    [
        "skip",
        "rename",
        "missing",
        "resource",
        "rejected-resource",
        "untyped",
        "duplicate",
    ],
)
def test_typed_planner_rejected_collision_validation(control: str) -> None:
    """Only typed rejected capability evidence authorizes an unloaded skip."""
    target = PREFIX + "helper"
    graph = inventory_graph(
        {"capabilities": {"helper": {}, "other": {}}, "resources": {"guide": {}}}
    )
    diagnostic = Diagnostic("inventory.invalid-payload", target, "Rejected body")
    graph = replace(
        graph,
        capabilities=tuple(
            item for item in graph.capabilities if str(item.id) != target
        ),
        rejected=() if control == "untyped" else (CapabilityId.parse(target),),
        diagnostics=(diagnostic,),
    )
    if control == "rejected-resource":
        graph = replace(
            graph,
            resources=(),
            rejected=(
                *graph.rejected,
                ResourceId.parse("fixture/tools:resource/guide"),
            ),
        )
    decision = (
        "fixture/tools:resource/guide"
        if control in {"resource", "rejected-resource"}
        else PREFIX + "absent" if control == "missing" else target
    )
    answer = Collision(
        capability=decision,
        action="rename" if control == "rename" else "skip",
        name="consumer-name" if control == "rename" else None,
    )
    result = select(
        graph,
        overrides=Overrides(
            collisions=(answer, answer) if control == "duplicate" else (answer,)
        ),
    )
    assert_that(result.valid).is_equal_to(control == "skip")
    entries = {item.id: item for item in result.capabilities}
    codes = [item.code for item in result.diagnostics]
    if control in {"skip", "duplicate"}:
        assert_that(entries[target].state).is_equal_to("excluded")
        assert_that(codes).does_not_contain("inventory.invalid-payload")
    else:
        assert_that(codes).contains("inventory.invalid-payload")
    if control != "skip":
        assert_that(codes).contains("selection.invalid-collision-override")


@pytest.mark.parametrize(
    "code",
    [
        "inventory.duplicate-id",
        "inventory.self-requires",
        "inventory.vendor-unavailable",
        "inventory.invalid-mapping",
        "invalid-id",
    ],
)
def test_rejected_skip_keeps_structural_and_acquisition_errors(code: str) -> None:
    """A valid skip cannot trim any structural or acquisition failure."""
    graph = replace(
        inventory_graph({}),
        rejected=(CapabilityId.parse(PREFIX + "helper"),),
        diagnostics=(Diagnostic(code, PREFIX + "helper", "failure"),),
    )
    result = select(
        graph,
        overrides=Overrides(
            collisions=(Collision(capability=PREFIX + "helper", action="skip"),)
        ),
    )
    assert_that(result.valid).is_false()
    assert_that(result.capabilities[0].state).is_equal_to("excluded")
    assert_that([item.code for item in result.diagnostics]).contains(code)
