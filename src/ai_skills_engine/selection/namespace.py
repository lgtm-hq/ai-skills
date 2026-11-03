"""Global catalog namespace validation, reserving aliases before selection."""

from collections import defaultdict
from collections.abc import Mapping

from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.manifest.overrides import Overrides
from ai_skills_engine.selection.closure import dependency_chain
from ai_skills_engine.selection.diagnostic import SelectionDiagnostic


def names_and_skips(
    *,
    capabilities: Mapping[str, Capability],
    overrides: Overrides | None,
) -> tuple[dict[str, tuple[str, ...]], set[str], set[str], list[SelectionDiagnostic]]:
    """Replay persistent names and skips without changing qualified identity.

    Args:
        capabilities: Unfiltered catalog.
        overrides: Consumer persisted decisions.

    Returns:
        Effective names, skipped IDs, reserved alias owners and invalid findings.
    """
    names = {
        key: item.aliases or item.destination_names or (item.id.name,)
        for key, item in capabilities.items()
    }
    reserved = {key for key, item in capabilities.items() if item.aliases}
    skips: set[str] = set()
    findings: list[SelectionDiagnostic] = []
    decisions: set[str] = set()
    for override in overrides.collisions if overrides else ():
        identity = override.capability
        if identity not in capabilities or identity in decisions:
            findings.append(
                SelectionDiagnostic(
                    code="selection.invalid-collision-override",
                    location=identity,
                    message="Collision override is stale or duplicated",
                    chain=(identity,),
                    fix=(
                        "Declare exactly one collision decision for an existing "
                        "qualified capability ID."
                    ),
                )
            )
        decisions.add(identity)
        if override.action == "rename" and override.name:
            names[identity] = (override.name,)
            reserved.add(identity)
        elif override.action == "skip":
            skips.add(identity)
    return names, skips, reserved, findings


def check_namespace(
    *,
    capabilities: Mapping[str, Capability],
    names: Mapping[str, tuple[str, ...]],
    kept: set[str],
    reserved: set[str],
    parents: Mapping[str, str | None],
) -> tuple[tuple[tuple[str, str, tuple[str, ...]], ...], list[SelectionDiagnostic]]:
    """Report collisions even for identical catalog bytes or unselected aliases.

    Role/name is the conservative shared host namespace; adapters may impose
    additional destination restrictions in subsequent projection work.

    Args:
        capabilities: Unfiltered records, including alias owners selected out.
        names: Effective names after explicit renames.
        kept: Capabilities surviving selection.
        reserved: Alias owners whose names were reserved before selection.
        parents: Shortest dependency witnesses.

    Returns:
        Namespace report and non-interactive conflict errors.
    """
    owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    for identity, capability in capabilities.items():
        if identity in kept or identity in reserved:
            for name in names[identity]:
                owners[(str(capability.role), name)].add(identity)
    report = tuple(
        (role, name, tuple(sorted(ids))) for (role, name), ids in sorted(owners.items())
    )
    findings = []
    for role, name, ids in report:
        affected = kept.intersection(ids)
        if len(ids) > 1 and affected:
            chains = [dependency_chain(parents=parents, target=key) for key in affected]
            findings.append(
                SelectionDiagnostic(
                    code="selection.namespace-collision",
                    location=f"{role}/{name}",
                    message=f"Reserved destination {role}/{name}: {', '.join(ids)}",
                    chain=min(chains, key=lambda chain: (len(chain), chain)),
                    fix=(
                        "Declare overrides.collisions rename or skip, or exclude "
                        "a conflicting capability; reserved aliases require an "
                        "explicit rename."
                    ),
                )
            )
    return report, findings
