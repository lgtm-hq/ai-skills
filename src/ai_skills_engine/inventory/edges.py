"""Resolve only declared selectors; prose and links never enter this layer."""

from collections.abc import Iterable
from dataclasses import replace

from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.capability_id import CapabilityId
from ai_skills_engine.inventory.pending import PendingCapability
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.migrations import migrate


def matches(*, selector: str, identity: str) -> bool:
    """Match an exact qualified ID, package or validated trailing wildcard.

    Args:
        selector: Schema-validated manifest selector.
        identity: Exact capability or resource identity.

    Returns:
        Whether the declaration names this identity.
    """
    if selector.endswith("*"):
        return identity.startswith(selector[:-1])
    return identity == selector or identity.startswith((selector + ":", selector + "/"))


def resolve_edges(
    *,
    pending: Iterable[PendingCapability],
    resource_ids: tuple[ResourceId, ...],
    publishers: set[str],
    migrations: dict[str, str],
) -> tuple[tuple[Capability, ...], tuple[Diagnostic, ...]]:
    """Expand declared selectors against the observed inventory, without closure.

    Args:
        pending: Complete source observations.
        resource_ids: Declared resources.
        publishers: Local and explicitly imported publisher namespaces.
        migrations: Consumer-declared old to current ID relationships.

    Returns:
        Capabilities with resolved direct edges and all invalid-target errors.
    """
    records = tuple(pending)
    ids = tuple(item.capability.id for item in records)
    diagnostics: list[Diagnostic] = []
    result: list[Capability] = []

    def resolve[Id: (CapabilityId, ResourceId)](
        *,
        item: PendingCapability,
        field: str,
        candidates: tuple[Id, ...],
    ) -> tuple[Id, ...]:
        """Resolve a declared field while preserving the target ID type."""
        resolved: set[Id] = set()
        for selector in getattr(item.declaration, field):
            target = migrate(selector=selector, migrations=migrations)
            found = {
                identity
                for identity in candidates
                if matches(selector=target, identity=str(identity))
            }
            if not found:
                code = f"inventory.unknown-{field}"
                if field == "requires" and target.split("/", 1)[0] not in publishers:
                    code = "inventory.non-imported-requires"
                diagnostics.append(
                    Diagnostic(
                        code,
                        str(item.capability.id),
                        f"{field} target is unavailable: {selector}",
                    )
                )
            if field == "requires" and item.capability.id in found:
                diagnostics.append(
                    Diagnostic(
                        "inventory.self-requires",
                        str(item.capability.id),
                        f"Self requires: {selector}",
                    )
                )
            resolved.update(found)
        return tuple(sorted(resolved, key=str))

    for item in records:
        result.append(
            replace(
                item.capability,
                requires=resolve(item=item, field="requires", candidates=ids),
                related=resolve(item=item, field="related", candidates=ids),
                resources=resolve(
                    item=item, field="resources", candidates=resource_ids
                ),
            )
        )
    return tuple(result), tuple(diagnostics)
