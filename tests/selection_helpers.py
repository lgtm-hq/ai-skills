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
