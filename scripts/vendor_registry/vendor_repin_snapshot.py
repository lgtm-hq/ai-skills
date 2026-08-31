"""Bake snapshot used to diff a vendor pin before and after re-pin."""

from __future__ import annotations

from dataclasses import dataclass

from vendor_registry.plugin_bake_result import PluginBakeResult
from vendor_registry.vendor import Vendor


@dataclass(frozen=True)
class VendorRepinSnapshot:
    """Skill, coverage, and collision state for one vendor after a bake.

    ``collisions`` is the global catalog collision report (skill explode
    names plus agent stems). A re-pin can introduce collisions against
    other vendors or first-party skills even when this vendor's own
    explode names look unique in isolation.
    """

    vendor_id: str
    sha: str
    explode_names: frozenset[str]
    skipped: tuple[str, ...]
    ingested_count: int
    collisions: tuple[str, ...]
    skill_digests: tuple[tuple[str, str], ...]


def snapshot_for_vendor(
    *,
    vendor: Vendor,
    results: tuple[PluginBakeResult, ...],
    skipped_by_vendor: dict[str, tuple[str, ...]],
    ingested_counts: dict[str, int],
    skill_collisions: tuple[str, ...],
    agent_collisions: tuple[str, ...],
    skill_digests: dict[str, dict[str, str]],
) -> VendorRepinSnapshot:
    """Project a full bake onto one vendor's plugin slices.

    Args:
        vendor: Registry vendor being re-pinned.
        results: Bake results for every declared plugin.
        skipped_by_vendor: Un-ingested ``SKILL.md`` paths keyed by vendor id.
        ingested_counts: Ingested skill counts keyed by vendor id.
        skill_collisions: Global explode-name collision lines.
        agent_collisions: Global agent-stem collision lines.
        skill_digests: Plugin id → explode name → ``SKILL.md`` SHA-256.

    Returns:
        Snapshot covering this vendor's slices plus the global collision
        report from the same bake.
    """
    plugin_ids = {plugin.id for plugin in vendor.plugins}
    explode_names = frozenset(
        name
        for result in results
        if result.plugin_id in plugin_ids
        for name in result.explode_names
    )
    digests = tuple(
        sorted(
            (name, digest)
            for plugin_id, names in skill_digests.items()
            if plugin_id in plugin_ids
            for name, digest in names.items()
        ),
    )
    return VendorRepinSnapshot(
        vendor_id=vendor.id,
        sha=vendor.sha,
        explode_names=explode_names,
        skipped=skipped_by_vendor.get(vendor.id, ()),
        ingested_count=ingested_counts.get(vendor.id, 0),
        collisions=(*skill_collisions, *agent_collisions),
        skill_digests=digests,
    )
