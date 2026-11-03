"""Reusable fixture inventories, immutable changes and pure selection helpers."""

import json
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from ai_skills_engine.inventory.model import (
    Capability,
    CapabilityId,
    Dialect,
    Inventory,
    PackageId,
    Resource,
    ResourceId,
    Role,
)
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.selection import SelectionResult, SelectionScope, select

PREFIX = "fixture/tools:skill/"
RESOURCE = "fixture/tools:resource/shared"


def inventory_graph(data: dict[str, Any]) -> Inventory:
    """Build immutable inventory records from the explicit graph fixture.

    Args:
        data: Capability/resource graph with optional origin and alias data.

    Returns:
        Complete inventory, with mentions as advisory inventory diagnostics.
    """
    package = PackageId.parse("fixture/tools")
    capabilities = []
    diagnostics = []
    for name, node in data.get("capabilities", {}).items():
        identity = CapabilityId.parse(PREFIX + name)
        capabilities.append(
            Capability(
                id=identity,
                package=package,
                role=Role.SKILL,
                dialect=Dialect.AGENT_SKILLS,
                origin=node.get("origin", "github.com/fixture/catalog"),
                source_path=PurePosixPath("skills/" + name),
                payload=(),
                tree_digest="same-bytes",
                requires=tuple(
                    CapabilityId.parse(PREFIX + target)
                    for target in node.get("requires", ())
                ),
                related=tuple(
                    CapabilityId.parse(PREFIX + target)
                    for target in node.get("related", ())
                ),
                resources=tuple(
                    ResourceId.parse("fixture/tools:resource/" + target)
                    for target in node.get("resources", ())
                ),
                aliases=tuple(node.get("aliases", ())),
            )
        )
        for target in node.get("mentions", ()):
            diagnostics.append(
                Diagnostic(
                    "inventory.undeclared-mention",
                    str(identity),
                    f"Mention of {PREFIX + target} without requires/related",
                    warning=True,
                )
            )
    return Inventory(
        capabilities=tuple(capabilities),
        resources=tuple(
            Resource(
                id=ResourceId.parse("fixture/tools:resource/" + name),
                origin=node.get("origin", "github.com/fixture/catalog"),
                source_path=PurePosixPath("shared/" + name),
                payload=(),
                tree_digest="same-bytes",
            )
            for name, node in data.get("resources", {}).items()
        ),
        diagnostics=tuple(diagnostics),
    )


@pytest.fixture
def selection_inventory() -> Inventory:
    """Load the named hard cases from a checked-in inventory fixture.

    Returns:
        Complete selection graph.
    """
    return inventory_graph(
        json.loads(
            (Path(__file__).parent / "fixtures/selection/graph.json").read_text()
        )
    )


def plan(
    inventory: Inventory,
    *,
    include: tuple[str, ...] | None = None,
    exclude: tuple[str, ...] = (),
    **kwargs: Any,
) -> SelectionResult:
    """Apply fixture-wide selectors using the public pure planner.

    Args:
        inventory: Complete observations.
        include: Absent or explicit qualified roots.
        exclude: Qualified vetoes.
        kwargs: Policy and persisted decisions.

    Returns:
        Full selection result.
    """
    members = tuple(
        str(item.id) for item in (*inventory.capabilities, *inventory.resources)
    )
    return select(
        inventory,
        scopes=(
            SelectionScope(
                location="fixture/tools",
                members=members,
                include=include,
                exclude=exclude,
            ),
        ),
        **kwargs,
    )


def selected(result: SelectionResult) -> set[str]:
    """Get the successfully retained capability identities.

    Args:
        result: Selection output.

    Returns:
        Selected roots and pulled-in dependencies.
    """
    return {
        item.id
        for item in result.capabilities
        if item.state in {"selected", "pulled-in"}
    }


def errors(result: SelectionResult) -> list[Any]:
    """Get errors without discarding the original diagnostic fields.

    Args:
        result: Plan result.

    Returns:
        Non-warning diagnostics.
    """
    return [item for item in result.diagnostics if not item.warning]


def change(inventory: Inventory, name: str, **kwargs: Any) -> Inventory:
    """Change exactly one immutable fixture record.

    Args:
        inventory: Original graph.
        name: Short capability identity.
        kwargs: Dataclass fields to replace.

    Returns:
        Updated graph with original order and evidence preserved.
    """
    return replace(
        inventory,
        capabilities=tuple(
            replace(item, **kwargs) if item.id.name == name else item
            for item in inventory.capabilities
        ),
    )


def edge_diagnostic_case(
    *, root: Path, vendor: Path, source: str, edge: str, control: str
) -> tuple[str, str, tuple[str, ...]]:
    """Prepare real source declarations with an unavailable required target.

    Args:
        root: Consumer fixture root.
        vendor: Offline vendor fixture.
        source: Local, mapped or vendor-manifest requiring declaration.
        edge: Rejected/missing capability/resource or nonimported requirement.
        control: Excluded, narrow, kept, required, transitive or stale selection.

    Returns:
        Requirer, target and shortest retained witness (empty when unselected).
    """
    document = read_document(root / "ai-skills.yaml")
    package = document["packages"][0]
    imported = document["vendors"][0]
    package["include"] = []
    imported["include"] = []
    package["capabilities"][0]["requires"] = []
    publisher = "fixture" if source == "local" else "vendor"
    owner = root if source == "local" else vendor
    boundary = package if source == "local" else imported
    declaration = (
        package["capabilities"][0]
        if source == "local"
        else imported["mapping"]["packages"][0]["capabilities"]["help"]
    )
    requirer = f"{publisher}/tools:skill/" + (
        "stable" if source == "local" else "helper"
    )
    vendor_package: dict[str, Any] = {
        "id": "tools",
        "capabilities": [{"id": "helper", "path": "skills/help"}],
    }
    if source == "manifest":
        imported.pop("mapping")
        declaration = vendor_package["capabilities"][0]
        (vendor / "skills/help/SKILL.md").write_text(
            "---\nname: help\ndescription: Helper.\n---\n"
        )
    resource = edge.startswith("resources")
    target = f"{publisher}/tools:{'resource' if resource else 'skill'}/broken"
    if edge == "nonimported":
        target = "absent/tools:skill/broken"
    declaration["resources" if resource else "requires"] = [target]
    rejected = edge.endswith("rejected")
    if rejected:
        if resource:
            record = {"id": "broken", "path": "absent.txt"}
            if source == "mapped":
                imported["mapping"]["packages"][0]["extraFiles"].append("broken.txt")
            else:
                (package if source == "local" else vendor_package).setdefault(
                    "resources", []
                ).append(record)
        else:
            broken = owner / "skills/broken"
            broken.mkdir()
            (broken / "SKILL.md").write_text("---\nname: broken\n---\nbody\n")
            if source != "mapped":
                (package if source == "local" else vendor_package)[
                    "capabilities"
                ].append({"id": "broken", "path": "skills/broken"})
        if control != "required":
            boundary["exclude"] = [target]
    chain: tuple[str, ...] = ()
    if control in {"excluded", "kept", "stale"}:
        boundary["include"] = [requirer]
        if control == "excluded":
            boundary.setdefault("exclude", []).append(requirer)
        elif control == "stale":
            boundary.setdefault("exclude", []).append(
                f"{publisher}/tools:skill/previous"
            )
        else:
            chain = (requirer, target)
    elif control in {"required", "transitive"}:
        for name in ("entry", "middle"):
            payload = root / "skills" / name
            payload.mkdir()
            (payload / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Test root.\n---\n"
            )
            package["capabilities"].append(
                {
                    "id": name,
                    "path": f"skills/{name}",
                    "requires": [requirer],
                }
            )
        package["include"] = [PREFIX + "entry"]
        chain = (PREFIX + "entry", requirer, target)
        if control == "transitive":
            package["capabilities"][-2]["requires"] = [PREFIX + "middle"]
            chain = (PREFIX + "entry", PREFIX + "middle", requirer, target)
    if source == "manifest":
        (vendor / "ai-skills.yaml").write_text(
            dump_document(
                {
                    "apiVersion": "ai-skills.dev/v1",
                    "publisher": {"id": "vendor"},
                    "packages": [vendor_package],
                }
            )
        )
    (root / "ai-skills.yaml").write_text(dump_document(document))
    (root / "ai-skills.lock").write_bytes(b"unchanged lock\n")
    (root / "installed-generation").write_bytes(b"unchanged generation\n")
    return requirer, target, chain


def collision_migration_case(
    *, root: Path, control: str, action: str, kind: str
) -> str:
    """Prepare persisted collision decisions over a renamed qualified identity.

    Args:
        root: Consumer fixture root.
        control: Migrated/current decision or stale/malformed/cycle/duplicate input.
        action: Rename or skip collision decision.
        kind: Capability or package migration.

    Returns:
        Current capability identity.
    """
    document = read_document(root / "ai-skills.yaml")
    current = PREFIX + "stable"
    previous = PREFIX + "previous" if kind == "capability" else "old/tools:skill/stable"
    migrations = [
        {
            "from": previous if kind == "capability" else "old/tools",
            "to": current if kind == "capability" else "fixture/tools",
        }
    ]
    identity = current if control == "current" else previous
    if control == "stale":
        migrations = []
    elif control == "malformed":
        identity = "previous"
    elif control == "cycle":
        migrations.append({"from": current, "to": previous})
    decision = {
        "capability": identity,
        "action": action,
        **({"name": "renamed"} if action == "rename" else {}),
    }
    document["overrides"] = {"migrations": migrations, "collisions": [decision]}
    if control == "duplicate":
        document["overrides"]["collisions"].append({**decision, "capability": current})
    # Keep the cycle control at collision replay, rather than resolving a
    # preexisting related edge through the same intentionally cyclic map.
    document["vendors"][0]["mapping"]["packages"][0]["capabilities"]["help"][
        "related"
    ] = []
    payload = root / "skills/other"
    payload.mkdir()
    (payload / "SKILL.md").write_text(
        "---\nname: start\ndescription: Conflicting destination.\n---\n"
    )
    document["packages"][0]["capabilities"].append(
        {"id": "other", "path": "skills/other"}
    )
    (root / "ai-skills.yaml").write_text(dump_document(document))
    (root / "ai-skills.lock").write_bytes(b"unchanged lock\n")
    (root / "installed-generation").write_bytes(b"unchanged generation\n")
    return current
