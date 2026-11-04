"""Bind observed local publications to declared chains and identity migrations."""

from dataclasses import replace
from typing import Any

from jsonschema import Draft202012Validator

from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.identity import parse_id
from ai_skills_engine.manifest.migrations import migrate
from ai_skills_engine.provenance.authorship import Authorship
from ai_skills_engine.provenance.context import Context
from ai_skills_engine.provenance.hop import LineageHop
from ai_skills_engine.provenance.ingest import schema
from ai_skills_engine.provenance.model import Lineage, union_lineage


def hop_for(
    *, record: Capability | Resource, context: Context, renamed_from: str | None = None
) -> LineageHop:
    """Record an observed publication step and name transformations.

    Args:
        record: Observed payload.
        context: Current publication identity.
        renamed_from: Explicitly migrated predecessor absent from live inputs.

    Returns:
        Immutable hop with canonical digest.
    """
    # A differing frontmatter name alone does not prove a rewrite. Applied
    # frontmatter transforms are retained from the authenticated index instead.
    transforms = ("alias",) if isinstance(record, Capability) and record.aliases else ()
    return LineageHop(
        origin=context.origin,
        publisher=record.id.package.publisher,
        rev=context.rev,
        id=str(record.id),
        path=str(record.source_path),
        tree_digest="sha256:" + record.tree_digest,
        renamed_from=renamed_from,
        transforms=transforms,
    )


def metadata(
    *, document: dict[str, Any], publisher: str
) -> tuple[dict[str, str], tuple[Authorship, ...]]:
    """Read only well-formed publisher-local descriptive overrides.

    Args:
        document: Vendor declarations, possibly with ignored authority fields.
        publisher: Current stable publisher namespace.

    Returns:
        Identity migrations and authorship statements, never policy grants.
    """
    overrides = document.get("overrides")
    if not isinstance(overrides, dict):
        return {}, ()
    moves = overrides.get("migrations", [])
    candidates = (
        {
            item["from"]: item["to"]
            for item in moves
            if isinstance(item, dict)
            and all(
                isinstance(item.get(key), str) and item[key].startswith(publisher + "/")
                for key in ("from", "to")
            )
        }
        if isinstance(moves, list)
        else {}
    )
    migrations: dict[str, str] = {}
    for source, target in candidates.items():
        try:
            parse_id(source)
            parse_id(target)
        except ValueError:
            continue  # Ignored vendor overrides cannot authorize malformed IDs.
        migrations[source] = target
    statements = overrides.get("attestations", [])
    validator = Draft202012Validator(schema()["properties"]["attestations"]["items"])
    return migrations, (
        tuple(
            Authorship(
                capability=item["capability"], path=item["path"], reason=item["reason"]
            )
            for item in statements
            if validator.is_valid(item)
            and item["capability"].startswith(publisher + "/")
        )
        if isinstance(statements, list)
        else ()
    )


def bind_local[Record: (Capability, Resource)](
    *,
    record: Record,
    context: Context,
    declared: tuple[Lineage, ...],
    identities: tuple[str, ...],
    migrations: dict[str, str],
    statements: tuple[Authorship, ...],
    findings: list[Diagnostic],
    strict: bool,
) -> Record:
    """Bind an index to observed bytes and preserve explicitly migrated ancestry.

    Args:
        record: Local observed payload.
        context: Current publication identity.
        declared: Last-hop-authenticated index chains.
        identities: All live and rejected identities.
        migrations: Publisher-local moves.
        statements: Descriptive independently authored claims.
        findings: Retained diagnostic accumulator.
        strict: Final consumer strictness.

    Returns:
        Frozen payload with complete declared lineage.
    """
    identity = str(record.id)
    old = None
    invalid_sources: set[str] = set()
    for source in sorted(migrations):
        if source in identities:
            continue
        try:
            target = migrate(
                selector=source, migrations=migrations, identities=identities
            )
        except ValueError:
            # Selection retains ownership of invalid migration/collision answers.
            # Invalid metadata cannot authorize ancestry or a renamedFrom claim.
            invalid_sources.add(source)
            continue
        if target == identity:
            old = source
            break
    # Package migrations retain each capability/resource's name and role.
    if old is None:
        old = next(
            (
                source + identity[identity.index(":") :]
                for source, target in sorted(migrations.items())
                if ":" not in source
                and source not in invalid_sources
                and target == str(record.id.package)
                and not any(value.startswith(source + ":") for value in identities)
            ),
            None,
        )
    current: LineageHop = hop_for(record=record, context=context, renamed_from=old)
    chains: list[Lineage] = []
    chain: Lineage
    last: LineageHop
    for chain in declared:
        if chain.id not in {identity, old}:
            continue
        last = chain.lineage[-1]
        if last.publisher != record.id.package.publisher or (
            chain.id == identity
            and (last.path != current.path or last.tree_digest != current.tree_digest)
        ):
            findings.append(
                Diagnostic(
                    "provenance.unverifiable-lineage",
                    identity,
                    "Index path, digest or publisher differs from observed payload",
                    warning=not strict,
                )
            )
            continue
        if chain.id == old:
            chain = replace(chain, id=identity, lineage=(*chain.lineage, current))
        else:
            chain = replace(
                chain,
                lineage=(
                    *chain.lineage[:-1],
                    replace(
                        last,
                        transforms=tuple(
                            sorted({*last.transforms, *current.transforms})
                        ),
                        renamed_from=last.renamed_from or old,
                    ),
                ),
            )
        chains.append(chain)
    if not chains:
        chains = [Lineage(id=identity, lineage=(current,))]
    attached: tuple[Authorship, ...] = tuple(
        item for item in statements if item.capability == identity
    )
    published_chains: list[Lineage] = []
    existing: Lineage
    for existing in chains:
        attestations = tuple(
            sorted(
                {*existing.attestations, *attached},
                key=lambda item: (item.capability, item.path, item.reason),
            )
        )
        published_chains.append(replace(existing, attestations=attestations))
    return replace(
        record,
        origin=context.origin,
        lineage=union_lineage(tuple(published_chains)),
    )
