"""Live qualified identities take precedence over consumer and vendor migrations."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that
from selection_helpers import inventory_graph
from test_selection_revision import run_plan

from ai_skills_engine.inventory.capability_id import CapabilityId
from ai_skills_engine.inventory.load import load_inventory
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.migration import Migration
from ai_skills_engine.manifest.overrides import Overrides
from ai_skills_engine.selection.rules import select
from ai_skills_engine.selection.scope import SelectionScope

pytest_plugins = ["inventory_helpers"]


def live_migration_case(
    *,
    root: Path,
    vendor: Path,
    author: str,
    kind: str,
    rejected: bool = False,
    control: str = "exclude",
) -> tuple[str, str]:
    """Prepare a manifest-bearing vendor with an attempted live identity move.

    Args:
        root: Isolated consumer fixture.
        vendor: Isolated offline vendor fixture.
        author: Consumer or vendor author of migration metadata.
        kind: Capability, resource, package or package-resource migration.
        rejected: Keep the typed source declaration but omit its payload.
        control: Baseline, exclude, required, rename, skip or absent-old control.

    Returns:
        Original source identity and proposed replacement identity.
    """
    document = read_document(root / "ai-skills.yaml")
    package = document["packages"][0]
    package["include"] = []
    package["capabilities"][0]["requires"] = []
    imported = document["vendors"][0]
    imported.pop("mapping")
    resource = "resource" in kind
    package_move = kind.startswith("package")
    role = "resource" if resource else "skill"
    target = f"vendor/tools:{role}/helper"
    replacement = f"vendor/{'replacement' if package_move else 'tools'}:{role}/"
    replacement += "helper" if package_move else "other"
    for name in ("helper", "other"):
        payload = vendor / "skills" / name
        payload.mkdir(parents=True, exist_ok=True)
        (payload / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Inert migration fixture.\n---\n"
        )
    field = "resources" if resource else "capabilities"
    source_record = {
        "id": "helper",
        "path": (
            "absent.txt" if rejected else "NOTICE.md" if resource else "skills/helper"
        ),
    }
    replacement_record = {
        "id": "helper" if package_move else "other",
        "path": "NOTICE.md" if resource else "skills/other",
    }
    records = [] if control == "absent" else [source_record]
    packages: list[dict[str, Any]] = [{"id": "tools", field: records}]
    if package_move:
        packages.append({"id": "replacement", field: [replacement_record]})
    else:
        records.append(replacement_record)
    vendor_document: dict[str, Any] = {
        "apiVersion": "ai-skills.dev/v1",
        "publisher": {"id": "vendor", "repo": "upstream/tools"},
        "packages": packages,
        "exports": [item["id"] for item in packages],
    }
    if control != "baseline":
        owner = document if author == "consumer" else vendor_document
        owner["overrides"] = {
            "migrations": [
                {
                    "from": "vendor/tools" if package_move else target,
                    "to": "vendor/replacement" if package_move else replacement,
                }
            ]
        }
    if control in {"rename", "skip"}:
        document.setdefault("overrides", {})["collisions"] = [
            {
                "capability": target,
                "action": control,
                **({"name": "consumer-name"} if control == "rename" else {}),
            }
        ]
    else:
        imported["exclude"] = ["vendor/tools" if package_move else target]
    if control in {"required", "absent"}:
        package["include"] = ["fixture/tools:skill/stable"]
        package["capabilities"][0]["resources" if resource else "requires"].append(
            target
        )
        imported["include"] = []
        if control == "absent":
            imported.pop("exclude")
    (root / "ai-skills.yaml").write_text(dump_document(document))
    (vendor / "ai-skills.yaml").write_text(dump_document(vendor_document))
    (root / "ai-skills.lock").write_bytes(b"unchanged lock\n")
    (root / "installed-generation").write_bytes(b"unchanged generation\n")
    return target, replacement


@pytest.mark.parametrize("author", ["vendor", "consumer"])
@pytest.mark.parametrize(
    "kind", ["capability", "package", "resource", "package-resource"]
)
@pytest.mark.parametrize("rejected", [False, True], ids=["live", "typed-rejected"])
@pytest.mark.parametrize("control", ["baseline", "exclude", "required", "absent"])
def test_actual_plan_migrations_preserve_existing_identity(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    author: str,
    kind: str,
    rejected: bool,
    control: str,
) -> None:
    """Actual load/CLI vetoes and shortest witnesses survive migration metadata."""
    root, vendor = inventory_repo
    target, replacement = live_migration_case(
        root=root,
        vendor=vendor,
        author=author,
        kind=kind,
        rejected=rejected,
        control=control,
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        """Prevent vendor execution and network acquisition during planning."""
        pytest.fail("planning must not execute code or acquire inputs")

    monkeypatch.setattr("subprocess.run", forbidden)
    output = run_plan(
        root=root,
        vendor=vendor,
        capsys=capsys,
        expected=1 if control == "required" else 0,
    )
    section = "resources" if "resource" in kind else "capabilities"
    entries = {item["id"]: item for item in output[section]}
    if control == "absent":
        assert_that(entries).does_not_contain(target)
        assert_that(entries[replacement]["state"]).is_equal_to("pulled-in")
    else:
        assert_that(entries[target]["state"]).is_equal_to("excluded")
        assert_that(entries[replacement]["state"]).is_equal_to(
            "excluded"
            if control == "required" or section == "resources"
            else "selected"
        )
    if control == "required":
        finding = next(
            item
            for item in output["diagnostics"]
            if item["code"] == "selection.required-excluded"
        )
        assert_that(finding["chain"]).is_equal_to(
            ["fixture/tools:skill/stable", target]
        )
        assert_that(finding["fix"]).is_not_empty()


@pytest.mark.parametrize("author", ["vendor", "consumer"])
@pytest.mark.parametrize("kind", ["capability", "package"])
@pytest.mark.parametrize("action", ["rename", "skip"])
@pytest.mark.parametrize("rejected", [False, True], ids=["live", "typed-rejected"])
def test_actual_plan_collision_answers_keep_live_identity(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    author: str,
    kind: str,
    action: str,
    rejected: bool,
) -> None:
    """A persisted consumer rename or skip cannot move to another live capability."""
    root, vendor = inventory_repo
    target, replacement = live_migration_case(
        root=root,
        vendor=vendor,
        author=author,
        kind=kind,
        control=action,
        rejected=rejected,
    )
    output = run_plan(
        root=root,
        vendor=vendor,
        capsys=capsys,
        expected=int(rejected and action == "rename"),
    )
    entries = {item["id"]: item for item in output["capabilities"]}
    if action == "skip":
        assert_that(entries[target]["state"]).is_equal_to("excluded")
    elif not rejected:
        assert_that(entries[target]["names"]).is_equal_to(["consumer-name"])
    else:
        assert_that(entries[target]["names"]).is_empty()
    assert_that(entries[replacement]["state"]).is_equal_to("selected")
    assert_that(entries[replacement]["names"]).does_not_contain("consumer-name")


@pytest.mark.parametrize(
    "kind", ["capability", "package", "resource", "package-resource"]
)
@pytest.mark.parametrize("rejected", [False, True], ids=["live", "typed-rejected"])
@pytest.mark.parametrize("consumer", [False, True], ids=["vendor", "consumer"])
def test_typed_planner_migrations_keep_vetoed_identities(
    kind: str,
    rejected: bool,
    consumer: bool,
) -> None:
    """Typed selection enforces precedence independently of the production loader."""
    resource = "resource" in kind
    graph = inventory_graph(
        {
            "capabilities": {"helper": {}, "other": {}},
            "resources": {"helper": {}, "other": {}},
        }
    )
    target = f"fixture/tools:{'resource' if resource else 'skill'}/helper"
    replacement = target.replace("/helper", "/other")
    if rejected:
        graph = replace(
            graph,
            capabilities=tuple(
                item for item in graph.capabilities if str(item.id) != target
            ),
            resources=tuple(item for item in graph.resources if str(item.id) != target),
            rejected=(
                ResourceId.parse(target) if resource else CapabilityId.parse(target),
            ),
        )
    members = tuple(str(item.id) for item in (*graph.capabilities, *graph.resources))
    migrations = (
        {"fixture/tools": "new/tools"}
        if kind.startswith("package")
        else {target: replacement}
    )
    result = select(
        graph,
        scopes=(
            SelectionScope(
                location="test", members=(*members, target), exclude=(target,)
            ),
        ),
        overrides=(
            Overrides(
                migrations=tuple(
                    Migration(from_=old, to=new) for old, new in migrations.items()
                )
            )
            if consumer
            else None
        ),
        migrations=None if consumer else migrations,
    )
    assert_that(result.valid).is_true()
    entries = {item.id: item for item in (*result.capabilities, *result.resources)}
    assert_that(entries[target].state).is_equal_to("excluded")


def test_absent_alias_stops_at_first_existing_identity(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Chained old IDs stop at a live intermediate for selectors and required edges."""
    root, vendor = inventory_repo
    target, replacement = live_migration_case(
        root=root,
        vendor=vendor,
        author="consumer",
        kind="capability",
        control="required",
    )
    document = read_document(root / "ai-skills.yaml")
    old = "vendor/tools:skill/old"
    document["overrides"]["migrations"].insert(0, {"from": old, "to": target})
    document["vendors"][0]["exclude"] = [old]
    document["packages"][0]["capabilities"][0]["requires"] = [old]
    (root / "ai-skills.yaml").write_text(dump_document(document))
    inventory = load_inventory(
        root, vendor_roots={"vendor": vendor}, selection_candidates=True
    )
    stable = next(
        item
        for item in inventory.capabilities
        if str(item.id) == "fixture/tools:skill/stable"
    )
    assert_that(tuple(map(str, stable.requires))).is_equal_to((target,))
    output = run_plan(root=root, vendor=vendor, capsys=capsys, expected=1)
    finding = next(
        item
        for item in output["diagnostics"]
        if item["code"] == "selection.required-excluded"
    )
    assert_that(finding["chain"]).is_equal_to(["fixture/tools:skill/stable", target])
    assert_that(finding["chain"]).does_not_contain(replacement)
