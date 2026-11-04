"""Byte-equality diagnostics scoped exclusively to declared pinned inputs."""

from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.vendor import Vendor
from ai_skills_engine.provenance.context import Context, origin_locator
from ai_skills_engine.provenance.input_files import input_files
from ai_skills_engine.provenance.origins import denied_origin


def diagnose(
    *,
    records: tuple[Capability | Resource, ...],
    vendors: tuple[Vendor, ...],
    roots: Mapping[str, Path],
    context: Context,
    resources: tuple[Resource, ...] = (),
    source_scoped: frozenset[str] = frozenset(),
) -> tuple[Diagnostic, ...]:
    """Compare shipped payload files with full import trees, without assigning origin.

    Args:
        records: This publisher's own shipped payloads with declared chains.
        vendors: This publisher's declared pins only.
        roots: Available snapshots of those imports.
        context: Final consumer policy and current publication identity.
        resources: Resolved required resource ancestry.
        source_scoped: Re-exports validated at their actual source publisher by
            the recursive builder, never inferred from a claimed chain or bytes.

    Returns:
        Missing-lineage and attestation-conflict evidence, never invented ancestry.
    """
    policy = context.policy
    provenance = policy.provenance if policy else None
    imports: dict[str, set[tuple[str, str]]] = {}
    findings: list[Diagnostic] = []
    for vendor in vendors:
        if vendor.id in roots:
            try:
                protected = tuple(
                    PurePosixPath(hop.path)
                    for record in (*records, *resources)
                    for chain in record.lineage
                    for hop in chain.lineage
                    if (hop.origin, hop.rev)
                    == (origin_locator(vendor.repo), vendor.sha)
                )
                files = input_files(root=roots[vendor.id], protected=protected)
            except (OSError, ValueError) as error:
                findings.append(
                    Diagnostic(
                        "provenance.unverifiable-lineage",
                        f"vendor:{vendor.id}",
                        "Cannot inspect full pinned input tree: "
                        + str(error).replace(str(roots[vendor.id]), vendor.id),
                        warning=not (provenance and provenance.mode == "strict"),
                    )
                )
                continue
            for file in files:
                imports.setdefault(file.sha256, set()).add(
                    (origin_locator(vendor.repo), vendor.sha)
                )
    resource_origins = {
        item.id: (
            item.origin,
            *(hop.origin for chain in item.lineage for hop in chain.lineage),
        )
        for item in resources
    }
    for record in records:
        identity = str(record.id)
        hops = tuple(hop for chain in record.lineage for hop in chain.lineage)
        ancestors = {
            (hop.origin, hop.rev)
            for chain in record.lineage
            for hop in chain.lineage[:-1]
            if (hop.origin, hop.rev) != (context.origin, context.rev)
        }
        statements = tuple(
            statement for chain in record.lineage for statement in chain.attestations
        )
        origins = (record.origin, *(hop.origin for hop in hops))
        if isinstance(record, Capability):
            origins += tuple(
                origin
                for target in record.resources
                for origin in resource_origins.get(target, ())
            )
        denied = denied_origin(origins=origins, policy=policy)
        blocked = set()
        for statement in statements:
            # A statement cannot contradict *any* imported ancestry, even if
            # the matching file differs, nor clear the final consumer's deny.
            matching_imports = {
                origin
                for file in record.payload
                if str(file.path) == statement.path
                for origin, _ in imports.get(file.sha256, set())
            }
            if (
                ancestors
                or denied
                or denied_origin(origins=sorted(matching_imports), policy=policy)
            ):
                blocked.add(statement)
                findings.append(
                    Diagnostic(
                        "provenance.attestation-conflicts-lineage",
                        identity,
                        f"{statement.path}: independent authorship conflicts "
                        "with known lineage or consumer deny",
                    )
                )
        if identity in source_scoped:
            # Its actual source's declared inputs were checked before re-export.
            # Keep the catalog's attestation-conflict checks above for every copy.
            continue
        for file in record.payload:
            corresponding = {(hop.origin, hop.rev) for hop in hops}
            missing = imports.get(file.sha256, set()) - corresponding
            if not missing:
                continue
            accepted = (
                bool(provenance and provenance.accept_attestations)
                and not ancestors
                and not denied
                and any(
                    statement.capability == identity
                    and statement.path == str(file.path)
                    and statement not in blocked
                    for statement in statements
                )
            )
            if not accepted:
                sources = ", ".join(
                    f"{origin}@{rev}" for origin, rev in sorted(missing)
                )
                findings.append(
                    Diagnostic(
                        "provenance.missing-lineage",
                        identity,
                        f"{file.path}: byte equality, not authorship, with declared "
                        f"pinned input(s) {sources}; corresponding lineage is missing",
                        warning=not (provenance and provenance.mode == "strict"),
                    )
                )
    return tuple(findings)
