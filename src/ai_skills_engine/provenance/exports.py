"""Preserve resource identity and all ancestry through explicit re-exports."""

from dataclasses import replace
from pathlib import Path, PurePosixPath

from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.payload import payload_files, source_path, tree_digest
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.identity import matches
from ai_skills_engine.manifest.vendor import Vendor
from ai_skills_engine.provenance.context import Context, origin_locator
from ai_skills_engine.provenance.model import Lineage, union_lineage
from ai_skills_engine.provenance.publisher import hop_for


def import_allowed(*, identity: str, vendor: Vendor) -> bool:
    """Keep recursive exports within the publisher's explicit import boundary.

    Args:
        identity: Exported identity.
        vendor: Publisher's pinned import declaration.

    Returns:
        Whether the publisher declared this import.
    """
    return (
        vendor.include is None
        or any(matches(selector=value, identity=identity) for value in vendor.include)
    ) and not any(
        matches(selector=value, identity=identity) for value in vendor.exclude or ()
    )


def merge_imports[Record: (Capability, Resource)](
    *,
    table: dict[str, Record],
    records: tuple[Record, ...],
    publisher: str,
    exports: set[str],
    vendor: Vendor,
    findings: list[Diagnostic],
    selection_candidates: bool,
) -> set[str]:
    """Combine only explicit exports, unioning every chain of a repeated identity.

    Args:
        table: Current candidate records.
        records: Recursively resolved vendor records.
        publisher: Imported manifest's publisher namespace.
        exports: That publisher's explicit exported packages.
        vendor: Current import declaration.
        findings: Retained duplicate identity evidence.
        selection_candidates: Retain consumer-vetoed records for plan explanations.

    Returns:
        Sources whose outgoing edge evidence now comes from the recursive input.
    """
    merged: set[str] = set()
    for item in records:
        key = str(item.id)
        direct = item.id.package.publisher == publisher
        if not direct and (
            str(item.id.package) not in exports
            or not any(
                (chain.lineage[-1].origin, chain.lineage[-1].rev)
                == (origin_locator(vendor.repo), vendor.sha)
                for chain in item.lineage
            )
            or (
                not selection_candidates
                and not import_allowed(identity=key, vendor=vendor)
            )
        ):
            continue
        if direct and key not in table:
            continue  # Preserve the inventory caller's direct import filters.
        if key in table and (
            table[key].origin != item.origin
            or table[key].tree_digest != item.tree_digest
            or table[key].payload != item.payload
        ):
            findings.append(
                Diagnostic(
                    "inventory.duplicate-id",
                    key,
                    "Recursive export origin or payload conflicts with another input",
                )
            )
            continue
        table[key] = replace(
            item,
            lineage=union_lineage(
                table[key].lineage if key in table else (), item.lineage
            ),
        )
        merged.add(key)
    return merged


def publish_exports[Record: (Capability, Resource)](
    *,
    table: dict[str, Record],
    root: Path,
    publisher: str,
    exports: set[str],
    context: Context,
    declared: tuple[Lineage, ...],
    findings: list[Diagnostic],
    strict: bool,
    vendors: tuple[Vendor, ...],
) -> None:
    """Append the current publisher and validate materialized resource copies.

    Args:
        table: Resolved records keyed by stable identity.
        root: Current publication snapshot.
        publisher: Current namespace.
        exports: Explicit package exports.
        context: Current origin and pin.
        declared: Current publication's authenticated chains.
        findings: Diagnostic accumulator.
        strict: Final consumer strictness.
        vendors: Publisher's import boundaries, which cannot be widened by exports.
    """
    for key, item in tuple(table.items()):
        if (
            item.id.package.publisher == publisher
            or str(item.id.package) not in exports
        ):
            continue
        if any(
            not import_allowed(identity=key, vendor=vendor)
            and any(
                (chain.lineage[-1].origin, chain.lineage[-1].rev)
                == (origin_locator(vendor.repo), vendor.sha)
                for chain in item.lineage
            )
            for vendor in vendors
        ):
            continue
        claimed = tuple(chain for chain in declared if chain.id == key)
        valid: list[Lineage] = []
        chain: Lineage
        for chain in claimed:
            last = chain.lineage[-1]
            try:
                payload = payload_files(source_path(root=root, relative=last.path))
                if (
                    last.publisher != publisher
                    or "sha256:" + tree_digest(payload) != last.tree_digest
                ):
                    raise ValueError("Materialized export publisher/digest mismatch")
                item = replace(
                    item,
                    source_path=PurePosixPath(last.path),
                    payload=payload,
                    tree_digest=tree_digest(payload),
                )
                valid.append(chain)
            except (OSError, ValueError) as error:
                findings.append(
                    Diagnostic(
                        "provenance.unverifiable-lineage",
                        key,
                        str(error).replace(str(root), "."),
                        warning=not strict,
                    )
                )
        current = replace(hop_for(record=item, context=context), publisher=publisher)
        # Known imported ancestry survives even if a supplied index omits it.
        inherited: list[Lineage] = []
        ancestor: Lineage
        for ancestor in item.lineage:
            inherited.append(replace(ancestor, lineage=(*ancestor.lineage, current)))
        table[key] = replace(
            item, lineage=union_lineage(tuple(inherited), tuple(valid))
        )
