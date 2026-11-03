"""Rebind explicitly declared unresolved edges after recursive exports are known."""

from dataclasses import replace

from ai_skills_engine.inventory.model import Inventory
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.manifest.identity import matches


def bind_exports(inventory: Inventory) -> Inventory:
    """Resolve only existing declarations; never infer dependencies from bytes.

    Args:
        inventory: Combined direct observations and recursive explicit exports.

    Returns:
        Inventory with newly available declared targets bound, preserving failures.
    """
    caps = {item.id: item for item in inventory.capabilities}
    resource_ids = tuple(item.id for item in inventory.resources)
    unresolved = []
    resolved: set[tuple[str, str]] = set()
    for edge in inventory.unresolved_edges:
        candidates = resource_ids if edge.field == "resources" else tuple(caps)
        found = tuple(
            identity
            for identity in candidates
            if matches(selector=edge.target, identity=str(identity))
        )
        if not found or edge.source not in caps:
            unresolved.append(edge)
            continue
        record = caps[edge.source]
        if edge.field == "resources":
            targets = tuple(
                sorted(
                    {
                        *record.resources,
                        *(item for item in found if isinstance(item, ResourceId)),
                    },
                    key=str,
                )
            )
            caps[edge.source] = replace(record, resources=targets)
        else:
            targets_caps = tuple(
                sorted(
                    {
                        *(
                            record.requires
                            if edge.field == "requires"
                            else record.related
                        ),
                        *(item for item in found if not isinstance(item, ResourceId)),
                    },
                    key=str,
                )
            )
            caps[edge.source] = (
                replace(record, requires=targets_caps)
                if edge.field == "requires"
                else replace(record, related=targets_caps)
            )
        resolved.add((str(edge.source), edge.target))
    settled = {
        (str(edge.source), edge.field)
        for edge in inventory.unresolved_edges
        if (str(edge.source), edge.target) in resolved
    } - {(str(edge.source), edge.field) for edge in unresolved}
    return replace(
        inventory,
        capabilities=tuple(sorted(caps.values(), key=lambda item: str(item.id))),
        unresolved_edges=tuple(unresolved),
        diagnostics=tuple(
            item
            for item in inventory.diagnostics
            if not (
                item.code
                in {
                    "inventory.unknown-requires",
                    "inventory.non-imported-requires",
                    "inventory.unknown-resources",
                    "inventory.unknown-related",
                }
                and (
                    (item.location, item.message.rsplit(": ", 1)[-1]) in resolved
                    or (item.location, item.code.rsplit("-", 1)[-1]) in settled
                )
            )
        ),
    )
