"""Pure dependency-aware selection over a complete pinned inventory."""

from collections.abc import Mapping

from ai_skills_engine.inventory.capability_id import CapabilityId
from ai_skills_engine.inventory.model import Inventory
from ai_skills_engine.manifest.overrides import Overrides
from ai_skills_engine.manifest.policy import Policy
from ai_skills_engine.selection.closure import closure, dependency_chain
from ai_skills_engine.selection.cycles import strongly_connected
from ai_skills_engine.selection.deny import deny_matches
from ai_skills_engine.selection.deny_subject import DenySubject
from ai_skills_engine.selection.diagnostic import SelectionDiagnostic
from ai_skills_engine.selection.entry import SelectionEntry
from ai_skills_engine.selection.model import SelectionResult
from ai_skills_engine.selection.namespace import check_namespace, names_and_skips
from ai_skills_engine.selection.scope import SelectionScope
from ai_skills_engine.selection.selectors import resolve_selectors
from ai_skills_engine.selection.state import State


def select(
    inventory: Inventory,
    *,
    scopes: tuple[SelectionScope, ...] | None = None,
    policy: Policy | None = None,
    overrides: Overrides | None = None,
    migrations: Mapping[str, str] | None = None,
) -> SelectionResult:
    """Resolve roots, closure, vetoes, advisory edges and namespace conflicts.

    Args:
        inventory: Complete candidate records, never a prefiltered import.
        scopes: Consumer package/vendor includes and excludes; None selects all.
        policy: Consumer-owned role constraints and origin denies.
        overrides: Explicit collision and migration declarations.
        migrations: Additional validated publisher-local identity migrations.

    Returns:
        Every input identity with its disposition and deterministic diagnostics.
        An invalid result preserves the requested roots and failure evidence.
    """
    caps = {str(item.id): item for item in inventory.capabilities}
    resources = {str(item.id): item for item in inventory.resources}
    all_ids = set(caps) | set(resources)
    rejected = {str(identity) for identity in inventory.rejected}
    candidate_caps = set(caps) | {
        str(identity)
        for identity in inventory.rejected
        if isinstance(identity, CapabilityId)
    }
    known_ids = all_ids | rejected
    candidate_resources = known_ids - candidate_caps
    if scopes is None:
        scopes = (
            SelectionScope(location="inventory", members=tuple(sorted(known_ids))),
        )
    migration_map = dict(migrations or {})
    migration_map.update(
        {item.from_: item.to for item in overrides.migrations} if overrides else {}
    )
    roots, excluded, findings = resolve_selectors(
        scopes=scopes,
        capabilities=candidate_caps,
        migrations=migration_map,
    )
    names, skips, reserved, namespace_findings = names_and_skips(
        capabilities=caps, overrides=overrides
    )
    findings.extend(namespace_findings)
    excluded.update({identity: "overrides.collisions: skip" for identity in skips})
    subjects = {
        key: DenySubject(id=key, origin=item.origin) for key, item in resources.items()
    }
    subjects.update(
        {
            key: DenySubject(
                id=key,
                origin=item.origin,
                resources=tuple(
                    subjects[str(target)]
                    for target in item.resources
                    if str(target) in subjects
                ),
            )
            for key, item in caps.items()
        }
    )
    denies = {
        key: match
        for key, subject in subjects.items()
        if (match := deny_matches(capability=subject, policy=policy)) is not None
    }
    blocked: dict[str, tuple[State, str]] = {
        key: (State.EXCLUDED, reason) for key, reason in excluded.items()
    }
    for key, capability in caps.items():
        if policy and policy.roles is not None and capability.role not in policy.roles:
            blocked[key] = (State.UNSUPPORTED, "role excluded by consumer policy.roles")
    for key, match in denies.items():
        if len(match.chain) == 1:
            blocked[key] = (
                State.DENIED,
                f"policy.deny.origins: {match.selector} (origin {match.origin})",
            )
    requires = {
        key: tuple(sorted(str(target) for target in item.requires))
        for key, item in caps.items()
    }
    graph = {
        key: tuple(
            sorted((*requires[key], *(str(target) for target in item.resources)))
        )
        for key, item in caps.items()
    }
    for edge in inventory.unresolved_edges:
        if edge.field != "related":
            source = str(edge.source)
            graph[source] = tuple(sorted({*graph.get(source, ()), edge.target}))
    parents = closure(
        graph=graph, roots=set(roots) - set(blocked), blocked=set(blocked)
    )
    kept = set(parents) - set(blocked)
    components: dict[str, tuple[str, ...]] = {}
    for component in strongly_connected(requires):
        if len(component) > 1:
            ordered = tuple(sorted(component))
            components.update(dict.fromkeys(component, ordered))
    for target in sorted(parents):
        if target in blocked:
            chain = dependency_chain(parents=parents, target=target)
            state, reason = blocked[target]
            findings.append(
                SelectionDiagnostic(
                    code=f"selection.required-{state}",
                    location=target,
                    message=f"{chain[0]} requires {target}, {reason}",
                    chain=chain,
                    fix=(
                        f"Also exclude {chain[0]}, or remove the blocking "
                        f"declaration for {target}."
                    ),
                    cycle=components.get(target, ()),
                )
            )
        elif target not in all_ids:
            chain = dependency_chain(parents=parents, target=target)
            findings.append(
                SelectionDiagnostic(
                    code="selection.required-missing",
                    location=target,
                    message=(
                        f"Required target {target} is absent from the pinned "
                        f"inventory"
                    ),
                    chain=chain,
                    fix=(
                        f"Restore the declared capability/resource {target} to "
                        f"vendor mapping/ingest, or exclude {chain[0]}."
                    ),
                )
            )
    # Only payload-scoped failures with trusted candidate evidence can be trimmed.
    # Unknown identities, duplicates and structural/acquisition failures stay fatal.
    for item in inventory.diagnostics:
        if item.code == "inventory.unknown-related":
            continue  # Structured targets below produce directional warnings.
        if (
            item.code
            in {
                "inventory.invalid-payload",
                "inventory.invalid-resource",
                "inventory.invalid-host-attribute",
                "inventory.undeclared-resource",
            }
            and item.location in known_ids
            and item.location not in kept
        ):
            continue
        chain = dependency_chain(parents=parents, target=item.location) or (
            item.location,
        )
        if item.code in {
            "inventory.unknown-requires",
            "inventory.unknown-resources",
            "inventory.non-imported-requires",
        }:
            chain = (*chain, item.message.rsplit(": ", 1)[-1])
        findings.append(
            SelectionDiagnostic(
                code=item.code,
                location=item.location,
                message=item.message,
                chain=chain,
                fix=(
                    "Repair the manifest/mapping or supply the complete "
                    "offline input before planning."
                ),
                warning=item.warning,
            )
        )
    related = {
        (key, str(target)) for key, item in caps.items() for target in item.related
    }
    related.update(
        (str(edge.source), edge.target)
        for edge in inventory.unresolved_edges
        if edge.field == "related"
    )
    for item in inventory.diagnostics:
        if item.code == "inventory.undeclared-mention" and item.message.startswith(
            "Mention of "
        ):
            related.add(
                (
                    item.location,
                    item.message.removeprefix("Mention of ").split(" without", 1)[0],
                )
            )
    dangling = tuple(
        sorted(
            (source, target)
            for source, target in related
            if source in kept and target not in kept
        )
    )
    for source, target in dangling:
        findings.append(
            SelectionDiagnostic(
                code="selection.dangling-related",
                location=source,
                message=(
                    f"{source} mentions missing {target}; related does not "
                    f"expand selection"
                ),
                chain=(*dependency_chain(parents=parents, target=source), target),
                fix=(
                    f"Select {target}, remove the advisory reference, or "
                    f"declare requires if invocation is necessary."
                ),
                warning=True,
            )
        )
    namespace, conflicts = check_namespace(
        capabilities=caps,
        names=names,
        kept=kept & set(caps),
        reserved=reserved,
        parents=parents,
    )
    findings.extend(conflicts)

    def entry(key: str) -> SelectionEntry:
        """Explain each record, preserving the highest-precedence veto."""
        chain = dependency_chain(parents=parents, target=key)
        state, reason = blocked.get(
            key,
            (
                State.EXCLUDED,
                "not included" if key in candidate_caps else "unused resource",
            ),
        )
        if key in kept:
            state = State.SELECTED if key in roots else State.PULLED_IN
            reason = roots[key] if key in roots else f"required by {parents[key]}"
            if key in denies:
                state = State.DENIED
                reason = (
                    f"required resource denied by policy.deny.origins: "
                    f"{denies[key].selector}"
                )
        return SelectionEntry(
            id=key,
            state=state,
            reason=reason,
            chain=chain or ((key,) if key in roots else ()),
            names=names.get(key, ()),
        )

    return SelectionResult(
        capabilities=tuple(entry(key) for key in sorted(candidate_caps)),
        resources=tuple(entry(key) for key in sorted(candidate_resources)),
        diagnostics=tuple(
            sorted(
                findings,
                key=lambda item: (item.location, item.code, item.chain, item.message),
            )
        ),
        dangling_related=dangling,
        namespace=namespace,
    )
