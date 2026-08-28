"""Coverage and global-namespace collision reports for vendor bake."""

from __future__ import annotations

from collections import defaultdict

from vendor_registry.plugin_bake_result import PluginBakeResult
from vendor_registry.vendor import Vendor

_GENERATED_HEADING = "do not edit — regenerate via scripts/bake_vendor_plugins.py"


def render_coverage_report(
    *,
    vendors: tuple[Vendor, ...],
    skipped_by_vendor: dict[str, tuple[str, ...]],
    ingested_counts: dict[str, int],
    fetched_vendors: frozenset[str],
    collisions: tuple[str, ...],
    agent_collisions: tuple[str, ...],
    explode_name_count: int,
) -> str:
    """Render the committed coverage / collision report.

    Args:
        vendors: Registry vendors in source order.
        skipped_by_vendor: Un-ingested ``SKILL.md`` paths per vendor id.
        ingested_counts: Ingested ``SKILL.md`` counts per vendor id.
        fetched_vendors: Vendor ids whose trees were materialized.
        collisions: Skill explode-name collision lines.
        agent_collisions: Agent-stem collision lines.
        explode_name_count: Unique baked skill names when clean.

    Returns:
        Markdown text with a trailing newline.
    """
    lines = [
        f"<!-- {_GENERATED_HEADING} -->",
        "",
        "# Vendor plugin bake coverage",
        "",
    ]
    if not any(vendor.plugins for vendor in vendors):
        lines.extend(
            [
                "No plugin slices are declared in `vendors.yaml`.",
                "Vendor trees were not fetched.",
                "Filling the five registered vendors is a separate issue.",
                "",
            ],
        )
    for vendor in vendors:
        if not vendor.plugins:
            lines.append(
                f"- `{vendor.id}`: index-only (no plugin slices declared).",
            )
            continue
        if vendor.id not in fetched_vendors:
            lines.append(f"- `{vendor.id}`: plugin slices declared but tree missing.")
            continue
        ingested = ingested_counts.get(vendor.id, 0)
        skipped = skipped_by_vendor.get(vendor.id, ())
        lines.append(
            f"- `{vendor.id}`: {ingested} ingested, {len(skipped)} SKILL.md skipped.",
        )
        for path in skipped:
            lines.append(f"  - SKIPPED `{path}`")
    lines.extend(["", "## Collision report", ""])
    if collisions or agent_collisions:
        lines.append(
            "Unresolved catalog-vs-catalog collisions (ADR-0005 class 2).",
        )
        lines.extend(f"- {line}" for line in collisions)
        lines.extend(f"- {line}" for line in agent_collisions)
    else:
        lines.append(
            f"Global namespace clean ({explode_name_count} unique skill names).",
        )
    lines.append("")
    return "\n".join(lines)


def collect_skill_collisions(
    *,
    results: tuple[PluginBakeResult, ...],
    first_party_names: frozenset[str],
) -> tuple[str, ...]:
    """Return skill explode-name collisions across plugins and first-party.

    Args:
        results: Baked plugin results.
        first_party_names: First-party ``skills/`` directory names.

    Returns:
        Stable collision lines. Empty when the namespace is clean.
    """
    owners: dict[str, list[str]] = defaultdict(list)
    for result in results:
        for name in result.explode_names:
            owners[name].append(result.plugin_id)
    lines: list[str] = []
    for name in sorted(owners):
        plugins = owners[name]
        if len(plugins) > 1:
            joined = ", ".join(plugins)
            lines.append(f"COLLIDES '{name}': {joined}")
        if name in first_party_names:
            joined = ", ".join(plugins)
            lines.append(
                f"COLLIDES '{name}': first-party skills/{name} vs {joined}",
            )
    return tuple(lines)


def collect_agent_collisions(
    *,
    results: tuple[PluginBakeResult, ...],
) -> tuple[str, ...]:
    """Return agent-stem collisions across baked plugins.

    Args:
        results: Baked plugin results.

    Returns:
        Stable collision lines. Empty when agent names are unique.
    """
    owners: dict[str, list[str]] = defaultdict(list)
    for result in results:
        for stem in result.agent_stems:
            owners[stem].append(result.plugin_id)
    return tuple(
        f"COLLIDES agent '{stem}': {', '.join(plugins)}"
        for stem, plugins in sorted(owners.items())
        if len(plugins) > 1
    )


def collision_error_message(
    *,
    skill_collisions: tuple[str, ...],
    agent_collisions: tuple[str, ...],
) -> str:
    """Build the fail-closed error for unresolved namespace collisions.

    Args:
        skill_collisions: Skill explode-name collision lines.
        agent_collisions: Agent-stem collision lines.

    Returns:
        Multi-line error message.
    """
    if skill_collisions:
        header = (
            "COLLISION REPORT: catalog plugins share explode names. "
            "Declare renameSkills (or slice one side out) in vendors.yaml."
        )
    else:
        header = (
            "COLLISION REPORT: catalog plugins share agent stems. "
            "Slice agents or change a stem in vendors.yaml."
        )
    return "\n".join((header, *skill_collisions, *agent_collisions))
