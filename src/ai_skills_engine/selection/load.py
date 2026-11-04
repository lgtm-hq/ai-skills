"""Bind offline inventory observations to consumer-owned selection declarations."""

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.load import load_inventory
from ai_skills_engine.inventory.model import Inventory
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.manifest.identity import parse_id
from ai_skills_engine.manifest.load import load_consumer, read_document
from ai_skills_engine.provenance.context import origin_locator
from ai_skills_engine.selection.diagnostic import SelectionDiagnostic
from ai_skills_engine.selection.model import SelectionResult
from ai_skills_engine.selection.rules import select
from ai_skills_engine.selection.scope import SelectionScope


def load_inputs(
    root: Path,
    *,
    vendor_roots: Mapping[str, Path] | None = None,
) -> tuple[Inventory, SelectionResult]:
    """Plan complete offline inputs without acquiring or executing vendor content.

    Args:
        root: Consumer repository.
        vendor_roots: Explicit vendor snapshots keyed by consumer alias.

    Returns:
        Complete candidates and selection from the same observation lifetime.
    """
    roots = vendor_roots or {}
    consumer, imported, _ = load_consumer(root / "ai-skills.yaml", vendor_roots=roots)
    migrations: dict[str, str] = {}
    for vendor in consumer.vendors:
        publisher = (
            imported[vendor.id].publisher.id if vendor.id in imported else vendor.id
        )
        # Only publisher-local identity moves are usable metadata. This does
        # not import overrides, collision answers, policy or trust authority.
        vendor_root = roots.get(vendor.id)
        if vendor.id in imported and vendor_root:
            document = read_document(vendor_root / "ai-skills.yaml")
            overrides = document.get("overrides", {})
            if not isinstance(overrides, dict):
                raise TypeError("Vendor overrides must be an object")
            for migration in overrides.get("migrations", []):
                if not isinstance(migration, dict):
                    raise TypeError("Vendor identity migration must be an object")
                old, new = migration.get("from", ""), migration.get("to", "")
                if (
                    isinstance(old, str)
                    and isinstance(new, str)
                    and old.startswith(publisher + "/")
                    and new.startswith(publisher + "/")
                ):
                    parse_id(old)
                    parse_id(new)
                    if old in migrations and migrations[old] != new:
                        raise ValueError(f"Conflicting publisher migration for {old}")
                    migrations[old] = new
    inventory = load_inventory(
        root,
        vendor_roots=roots,
        selection_candidates=True,
        identity_migrations=migrations,
    )
    identities = tuple(
        sorted(
            [str(item.id) for item in inventory.capabilities]
            + [str(resource.id) for resource in inventory.resources]
            + [str(identity) for identity in inventory.rejected]
        )
    )
    scopes = [
        SelectionScope(
            location=f"{consumer.publisher.id}/{package.id}",
            members=tuple(
                key
                for key in identities
                if key.startswith(f"{consumer.publisher.id}/{package.id}:")
            ),
            include=package.include,
            exclude=package.exclude,
        )
        for package in consumer.packages
    ]
    for vendor in consumer.vendors:
        publisher = (
            imported[vendor.id].publisher.id if vendor.id in imported else vendor.id
        )
        records: tuple[Capability | Resource, ...] = (
            *inventory.capabilities,
            *inventory.resources,
        )
        exported = {
            str(item.id)
            for item in records
            if item.id.package.publisher != consumer.publisher.id
            and any(
                (hop.origin, hop.rev) == (origin_locator(vendor.repo), vendor.sha)
                for chain in item.lineage
                for hop in chain.lineage
            )
        }
        members = tuple(
            key
            for key in identities
            if key.startswith(publisher + "/") or key in exported
        )
        scopes.append(
            SelectionScope(
                location=f"vendor:{vendor.id}",
                members=members,
                include=vendor.include,
                exclude=vendor.exclude,
            )
        )
    result = select(
        inventory,
        scopes=tuple(scopes),
        policy=consumer.policy,
        overrides=consumer.overrides,
        migrations=migrations,
    )
    missing = tuple(
        SelectionDiagnostic(
            code="selection.vendor-unavailable",
            location=f"vendor:{vendor.id}",
            message=f"Pinned inventory for {vendor.repo}@{vendor.sha} is unavailable",
            chain=(),
            fix=f"Supply --vendor-root {vendor.id}=PATH for the pinned snapshot.",
        )
        for vendor in consumer.vendors
        if vendor.id not in roots and vendor.include != ()
    )
    return inventory, replace(
        result,
        diagnostics=tuple(
            sorted(
                (*result.diagnostics, *missing),
                key=lambda item: (item.location, item.code, item.chain, item.message),
            )
        ),
    )


def load_selection(
    root: Path, *, vendor_roots: Mapping[str, Path] | None = None
) -> SelectionResult:
    """Plan offline inputs through the shared inventory/selection boundary.

    Args:
        root: Consumer repository.
        vendor_roots: Explicit vendor snapshots keyed by consumer alias.

    Returns:
        Selection retaining the inventory's original diagnostics.
    """
    return load_inputs(root, vendor_roots=vendor_roots)[1]
