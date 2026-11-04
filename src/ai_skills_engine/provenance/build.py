"""Construct lineage at the inventory boundary, recursively resolving explicit pins."""

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.model import Inventory
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.model import Manifest
from ai_skills_engine.provenance.context import Context, origin_locator
from ai_skills_engine.provenance.diagnose import diagnose
from ai_skills_engine.provenance.edges import bind_exports
from ai_skills_engine.provenance.exports import merge_imports, publish_exports
from ai_skills_engine.provenance.ingest import ingest
from ai_skills_engine.provenance.publisher import bind_local, metadata
from ai_skills_engine.provenance.resources import recheck_resources


def build_inventory(
    *,
    inventory: Inventory,
    root: Path,
    roots: Mapping[str, Path],
    manifest: Manifest,
    context: Context,
    fetch_vendors: bool,
    selection_candidates: bool,
) -> Inventory:
    """Attach local chains, authenticate indexes and append every recursive export.

    Args:
        inventory: Raw direct inventory with all rejection/edge evidence.
        root: Current publisher snapshot.
        roots: Direct and slash-qualified nested vendor aliases.
        manifest: Current publication declarations.
        context: Expected pinned identity and final consumer policy.
        fetch_vendors: Whether explicit pinned acquisition is authorized.
        selection_candidates: Retain the final consumer's vetoed candidates.

    Returns:
        Deterministic inventory retaining provenance and acquisition failures.
    """
    from ai_skills_engine.inventory.load import _load_inventory

    findings = list(inventory.diagnostics)
    strict = bool(
        context.policy
        and context.policy.provenance
        and context.policy.provenance.mode == "strict"
    )
    try:
        declared = ingest(root=root, context=context)
    except (OSError, TypeError, ValueError) as error:
        declared = ()
        findings.append(
            Diagnostic(
                "provenance.unverifiable-lineage",
                "lineage",
                str(error).replace(str(root), "."),
                warning=not strict,
            )
        )
    document = read_document(root / "ai-skills.yaml")
    migrations, statements = metadata(
        document=document, publisher=manifest.publisher.id
    )
    statements = (*statements, *context.attestations)
    records: tuple[Capability | Resource, ...] = (
        *inventory.capabilities,
        *inventory.resources,
    )
    own = {
        str(item.id)
        for item in records
        if item.id.package.publisher == manifest.publisher.id
    }
    identities = tuple(str(item.id) for item in records) + tuple(
        map(str, inventory.rejected)
    )
    caps = {
        str(item.id): (
            bind_local(
                record=item,
                context=context,
                declared=declared,
                identities=identities,
                migrations=migrations,
                statements=statements,
                findings=findings,
                strict=strict,
            )
            if str(item.id) in own
            else item
        )
        for item in inventory.capabilities
    }
    resources = {
        str(item.id): (
            bind_local(
                record=item,
                context=context,
                declared=declared,
                identities=identities,
                migrations=migrations,
                statements=statements,
                findings=findings,
                strict=strict,
            )
            if str(item.id) in own
            else item
        )
        for item in inventory.resources
    }
    rejected = set(inventory.rejected)
    unresolved = set(inventory.unresolved_edges)
    recursive_sources: set[str] = set()
    source_scoped: set[str] = set()
    for vendor in manifest.vendors:
        vendor_root = roots.get(vendor.id)
        if vendor_root is None:
            if context.ancestors:
                findings.append(
                    Diagnostic(
                        "provenance.unverifiable-lineage",
                        f"vendor:{vendor.id}",
                        f"Pinned input {vendor.repo}@{vendor.sha} unavailable "
                        "for recursive provenance",
                        warning=not strict,
                    )
                )
            continue
        nested_roots = {
            key.removeprefix(vendor.id + "/"): value
            for key, value in roots.items()
            if key.startswith(vendor.id + "/")
        }
        imported_context = Context(
            origin=origin_locator(vendor.repo),
            rev=vendor.sha,
            policy=context.policy,
            ancestors=(*context.ancestors, (context.origin, context.rev)),
            attestations=context.attestations,
            migrations=context.migrations,
        )
        if (
            imported_context.origin,
            imported_context.rev,
        ) in imported_context.ancestors or len(imported_context.ancestors) > 64:
            findings.append(
                Diagnostic(
                    "provenance.reexport-cycle",
                    f"vendor:{vendor.id}",
                    "Re-export cycle: "
                    + " -> ".join(
                        origin
                        for origin, _ in (
                            *imported_context.ancestors,
                            (imported_context.origin, imported_context.rev),
                        )
                    ),
                )
            )
            continue
        if not (vendor_root / "ai-skills.yaml").is_file():
            mapped_migrations, mapped_statements = metadata(
                document=document, publisher=vendor.id
            )
            try:
                imported_chains = ingest(root=vendor_root, context=imported_context)
            except (OSError, TypeError, ValueError) as error:
                imported_chains = ()
                findings.append(
                    Diagnostic(
                        "provenance.unverifiable-lineage",
                        f"vendor:{vendor.id}",
                        str(error).replace(str(vendor_root), vendor.id),
                        warning=not strict,
                    )
                )

            for key, record in tuple(caps.items()):
                if record.id.package.publisher == vendor.id:
                    caps[key] = bind_local(
                        record=record,
                        context=imported_context,
                        declared=imported_chains,
                        identities=identities,
                        migrations=mapped_migrations,
                        statements=(*mapped_statements, *context.attestations),
                        findings=findings,
                        strict=strict,
                    )
                    source_scoped.add(key)
            for key, resource in tuple(resources.items()):
                if resource.id.package.publisher == vendor.id:
                    resources[key] = bind_local(
                        record=resource,
                        context=imported_context,
                        declared=imported_chains,
                        identities=identities,
                        migrations=mapped_migrations,
                        statements=(*mapped_statements, *context.attestations),
                        findings=findings,
                        strict=strict,
                    )
                    source_scoped.add(key)
            continue
        child = _load_inventory(
            root=vendor_root,
            vendor_roots=nested_roots,
            fetch_vendors=fetch_vendors,
            selection_candidates=True,
            identity_migrations={},
            context=imported_context,
            ingest_vendor=vendor,
        )
        child_doc = read_document(vendor_root / "ai-skills.yaml")
        publisher = child_doc["publisher"]["id"]
        exports = {
            value if "/" in value else publisher + "/" + value
            for value in child_doc.get("exports", ())
        }
        merged_sources = merge_imports(
            table=caps,
            records=child.capabilities,
            publisher=publisher,
            exports=exports,
            vendor=vendor,
            findings=findings,
            selection_candidates=selection_candidates,
        )
        merged_resources = merge_imports(
            table=resources,
            records=child.resources,
            publisher=publisher,
            exports=exports,
            vendor=vendor,
            findings=findings,
            selection_candidates=selection_candidates,
        )
        source_scoped.update(merged_sources | merged_resources)
        # The recursive pass sees the publisher's pins and validated identity
        # migrations. Replace provisional direct evidence once per source;
        # subsequent compatible inputs contribute additional edge evidence.
        replaced_sources = merged_sources - recursive_sources
        recursive_sources.update(merged_sources)
        findings = [
            item
            for item in findings
            if not (
                item.location in replaced_sources
                and item.code
                in {
                    "inventory.unknown-requires",
                    "inventory.unknown-related",
                    "inventory.unknown-resources",
                    "inventory.non-imported-requires",
                    "inventory.undeclared-resource",
                }
            )
        ]
        findings.extend(child.diagnostics)
        rejected.update(
            item
            for item in child.rejected
            if item.package.publisher == publisher or str(item.package) in exports
        )
        unresolved = {
            edge for edge in unresolved if str(edge.source) not in replaced_sources
        } | {
            edge
            for edge in child.unresolved_edges
            if str(edge.source) in merged_sources
        }
    exports = {
        value if "/" in value else manifest.publisher.id + "/" + value
        for value in manifest.exports
    }
    publish_exports(
        table=caps,
        root=root,
        publisher=manifest.publisher.id,
        exports=exports,
        context=context,
        declared=declared,
        findings=findings,
        strict=strict,
        vendors=manifest.vendors,
    )
    publish_exports(
        table=resources,
        root=root,
        publisher=manifest.publisher.id,
        exports=exports,
        context=context,
        declared=declared,
        findings=findings,
        strict=strict,
        vendors=manifest.vendors,
    )
    observed = {*caps, *resources}
    published_records: tuple[Capability | Resource, ...] = (
        *caps.values(),
        *resources.values(),
    )
    consumed = {
        hop.renamed_from
        for item in published_records
        for chain in item.lineage
        for hop in chain.lineage
    }
    for chain in declared:
        if chain.id not in observed | consumed:
            findings.append(
                Diagnostic(
                    "provenance.unverifiable-lineage",
                    chain.id,
                    "Index identity has no shipped payload",
                    warning=not strict,
                )
            )
    result = bind_exports(
        replace(
            inventory,
            capabilities=tuple(sorted(caps.values(), key=lambda item: str(item.id))),
            resources=tuple(sorted(resources.values(), key=lambda item: str(item.id))),
            rejected=tuple(sorted(rejected, key=str)),
            unresolved_edges=tuple(
                sorted(
                    unresolved,
                    key=lambda item: (str(item.source), item.field, item.target),
                )
            ),
            diagnostics=tuple(findings),
        )
    )
    result = recheck_resources(inventory=result, root=root, own=own, context=context)
    resolved_records: tuple[Capability | Resource, ...] = (
        *result.capabilities,
        *result.resources,
    )
    shipped = tuple(
        item
        for item in resolved_records
        if str(item.id) in own or str(item.id.package) in exports
    )
    findings = [
        *result.diagnostics,
        *diagnose(
            records=shipped,
            vendors=manifest.vendors,
            roots=roots,
            context=context,
            resources=result.resources,
            source_scoped=frozenset(source_scoped - own),
        ),
    ]
    return replace(
        result,
        diagnostics=tuple(
            sorted(
                set(findings),
                key=lambda item: (item.location, item.code, item.message, item.warning),
            )
        ),
    )
