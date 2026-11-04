"""Recheck real Markdown resource boundaries after recursive export resolution."""

from dataclasses import replace
from pathlib import Path

from ai_skills_engine.inventory.lint import lint_inventory
from ai_skills_engine.inventory.model import Inventory
from ai_skills_engine.inventory.payload import payload_files, source_path, tree_digest
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.provenance.context import Context


def recheck_resources(
    *, inventory: Inventory, root: Path, own: set[str], context: Context
) -> Inventory:
    """Re-evaluate links against observed materialized resources, never claimed paths.

    Args:
        inventory: Edge-resolved records including authenticated resource copies.
        root: Current publisher's safe snapshot.
        own: Local capability/resource identities.
        context: Current publisher identity, required before binding a local copy.

    Returns:
        Observations with provisional local link errors replaced only when all
        required resource boundaries are physically verified at this publisher.
    """
    paths: dict[ResourceId, Path] = {}
    for resource in inventory.resources:
        if str(resource.id) not in own and not any(
            (chain.lineage[-1].origin, chain.lineage[-1].rev, chain.lineage[-1].path)
            == (context.origin, context.rev, str(resource.source_path))
            for chain in resource.lineage
        ):
            continue  # Equal local bytes alone cannot bind an imported resource ID.
        try:
            source = source_path(root=root, relative=str(resource.source_path))
            if tree_digest(payload_files(source)) == resource.tree_digest:
                paths[resource.id] = source
        except (OSError, ValueError):
            continue  # Remote resources retain the existing source's lint evidence.
    capabilities = tuple(
        item
        for item in inventory.capabilities
        if str(item.id) in own and all(target in paths for target in item.resources)
    )
    checked = {str(item.id) for item in capabilities}
    findings = lint_inventory(
        capabilities=capabilities,
        sources={
            item.id: source_path(root=root, relative=str(item.source_path))
            for item in capabilities
        },
        resource_paths=paths,
    )
    return replace(
        inventory,
        diagnostics=tuple(
            item
            for item in inventory.diagnostics
            if item.code != "inventory.undeclared-resource"
            or item.location not in checked
        )
        + tuple(
            item
            for item in findings
            if item.code
            in {"inventory.undeclared-resource", "inventory.invalid-payload"}
        ),
    )
