"""Qualified selector resolution before destination aliases or deduplication."""

from collections.abc import Collection, Mapping

from ai_skills_engine.manifest.identity import matches, parse_id
from ai_skills_engine.manifest.migrations import migrate
from ai_skills_engine.selection.diagnostic import SelectionDiagnostic
from ai_skills_engine.selection.scope import SelectionScope


def resolve_selectors(
    *,
    scopes: tuple[SelectionScope, ...],
    capabilities: set[str],
    migrations: Mapping[str, str],
    identities: Collection[str],
) -> tuple[dict[str, str], dict[str, str], list[SelectionDiagnostic]]:
    """Resolve roots and vetoes within their declaration's pinned inventory.

    Args:
        scopes: Local-package and vendor selection declarations.
        capabilities: Capability IDs, excluding resources as selection roots.
        migrations: Explicit identity migrations.
        identities: Complete observed IDs, including resources and rejected IDs.

    Returns:
        Root reasons, exclude reasons and actionable selector errors.
    """
    roots: dict[str, str] = {}
    excluded: dict[str, str] = {}
    findings: list[SelectionDiagnostic] = []
    for scope in sorted(scopes, key=lambda item: item.location):
        if scope.include is None:
            roots.update(
                {
                    identity: "default include " + scope.location
                    for identity in scope.members
                    if identity in capabilities
                }
            )
        for field, selectors in (
            ("include", scope.include),
            ("exclude", scope.exclude),
        ):
            for selector in sorted(selectors or ()):
                try:
                    parse_id(selector, selector=True)
                    target = migrate(
                        selector=selector, migrations=migrations, identities=identities
                    )
                    found = [
                        identity
                        for identity in scope.members
                        if matches(selector=target, identity=identity)
                        and (field == "exclude" or identity in capabilities)
                    ]
                except ValueError as error:
                    findings.append(
                        SelectionDiagnostic(
                            code="selection.invalid-selector",
                            location=scope.location,
                            message=str(error),
                            chain=(),
                            fix=(
                                "Use a qualified capability, resource exclusion, "
                                "package "
                                "or publisher selector; repair cyclic migrations."
                            ),
                        )
                    )
                    continue
                if not found:
                    findings.append(
                        SelectionDiagnostic(
                            code="selection.selector-unmatched",
                            location=scope.location,
                            message=(
                                f"{field}: {selector} matches no "
                                "pinned inventory item"
                            ),
                            chain=(),
                            fix=(
                                f"Update or remove {field}: {selector}, or declare an "
                                f"explicit identity migration."
                            ),
                        )
                    )
                destination = roots if field == "include" else excluded
                for identity in found:
                    destination.setdefault(identity, f"{field}: {selector}")
    return roots, excluded, findings
