"""Diff two vendor bake snapshots into a re-pin summary."""

from __future__ import annotations

import json
from dataclasses import dataclass

from vendor_registry.vendor_repin_snapshot import VendorRepinSnapshot


@dataclass(frozen=True)
class VendorRepinDiff:
    """Added, removed, renamed, coverage, and collision delta for one pin.

    Renames are digest matches: a removed explode name whose ``SKILL.md``
    hash equals an added explode name is reported as renamed and omitted
    from the added/removed lists.
    """

    vendor_id: str
    old_sha: str
    new_sha: str
    unchanged: bool
    added_skills: tuple[str, ...]
    removed_skills: tuple[str, ...]
    renamed_skills: tuple[tuple[str, str], ...]
    skipped_added: tuple[str, ...]
    skipped_removed: tuple[str, ...]
    ingested_before: int
    ingested_after: int
    collisions: tuple[str, ...]
    new_collisions: tuple[str, ...]


def diff_snapshots(
    *,
    before: VendorRepinSnapshot,
    after: VendorRepinSnapshot,
) -> VendorRepinDiff:
    """Compare two bake snapshots for the same vendor id.

    Args:
        before: Snapshot at the previous pin.
        after: Snapshot at the candidate pin.

    Returns:
        Structured delta. ``unchanged`` is true when the SHA is identical.

    Raises:
        ValueError: If the snapshots are for different vendor ids.
    """
    if before.vendor_id != after.vendor_id:
        msg = f"cannot diff snapshots for {before.vendor_id!r} and {after.vendor_id!r}"
        raise ValueError(msg)
    unchanged = before.sha == after.sha
    added = after.explode_names - before.explode_names
    removed = before.explode_names - after.explode_names
    before_by_digest = {digest: name for name, digest in before.skill_digests}
    renamed: list[tuple[str, str]] = []
    claimed_added: set[str] = set()
    claimed_removed: set[str] = set()
    for new_name, digest in after.skill_digests:
        old_name = before_by_digest.get(digest)
        if (
            old_name is not None
            and old_name != new_name
            and old_name in removed
            and new_name in added
            and old_name not in claimed_removed
            and new_name not in claimed_added
        ):
            renamed.append((old_name, new_name))
            claimed_added.add(new_name)
            claimed_removed.add(old_name)
    new_collisions = tuple(
        line for line in after.collisions if line not in set(before.collisions)
    )
    return VendorRepinDiff(
        vendor_id=before.vendor_id,
        old_sha=before.sha,
        new_sha=after.sha,
        unchanged=unchanged,
        added_skills=tuple(sorted(added - claimed_added)),
        removed_skills=tuple(sorted(removed - claimed_removed)),
        renamed_skills=tuple(sorted(renamed)),
        skipped_added=tuple(
            sorted(set(after.skipped) - set(before.skipped)),
        ),
        skipped_removed=tuple(
            sorted(set(before.skipped) - set(after.skipped)),
        ),
        ingested_before=before.ingested_count,
        ingested_after=after.ingested_count,
        collisions=after.collisions,
        new_collisions=new_collisions,
    )


def render_markdown(*, diff: VendorRepinDiff, display_ref: str | None) -> str:
    """Render a human-readable re-pin summary.

    Args:
        diff: Snapshot delta.
        display_ref: Registry ``displayRef`` shown in the pin line.

    Returns:
        Markdown text with a trailing newline.
    """
    ref = display_ref if display_ref is not None else "latest"
    lines = [f"# Vendor re-pin: `{diff.vendor_id}`", ""]
    if diff.unchanged:
        lines.extend(
            [
                f"Pin already at `{diff.new_sha}` (`displayRef: {ref}`).",
                "No bake delta.",
                "",
            ],
        )
        return "\n".join(lines)
    lines.extend(
        [
            f"- Pin: `{diff.old_sha}` → `{diff.new_sha}` (`displayRef: {ref}`)",
            f"- Ingested skills: {diff.ingested_before} → {diff.ingested_after}",
            "",
        ],
    )
    _append_list(lines=lines, heading="Added skills", items=diff.added_skills)
    _append_list(
        lines=lines,
        heading="Removed skills",
        items=diff.removed_skills,
    )
    if diff.renamed_skills:
        lines.extend(["## Renamed skills", ""])
        lines.extend(f"- `{old}` → `{new}`" for old, new in diff.renamed_skills)
        lines.append("")
    else:
        lines.extend(["## Renamed skills", "", "None.", ""])
    _append_list(
        lines=lines,
        heading="Newly skipped SKILL.md",
        items=diff.skipped_added,
    )
    _append_list(
        lines=lines,
        heading="No longer skipped SKILL.md",
        items=diff.skipped_removed,
    )
    lines.extend(["## Collisions", ""])
    if diff.collisions:
        lines.append(
            "Unresolved catalog collisions (fail closed). "
            "Declare `renameSkills` or slice one side out in `vendors.yaml`.",
        )
        lines.extend(f"- {line}" for line in diff.collisions)
    else:
        lines.append("None.")
    lines.append("")
    return "\n".join(lines)


def render_json(*, diff: VendorRepinDiff, display_ref: str | None) -> str:
    """Render a machine-readable re-pin summary.

    Args:
        diff: Snapshot delta.
        display_ref: Registry ``displayRef``.

    Returns:
        JSON object text with a trailing newline.
    """
    payload = {
        "vendorId": diff.vendor_id,
        "displayRef": display_ref,
        "oldSha": diff.old_sha,
        "newSha": diff.new_sha,
        "unchanged": diff.unchanged,
        "addedSkills": list(diff.added_skills),
        "removedSkills": list(diff.removed_skills),
        "renamedSkills": [{"from": old, "to": new} for old, new in diff.renamed_skills],
        "coverage": {
            "ingestedBefore": diff.ingested_before,
            "ingestedAfter": diff.ingested_after,
            "skippedAdded": list(diff.skipped_added),
            "skippedRemoved": list(diff.skipped_removed),
        },
        "collisions": list(diff.collisions),
        "newCollisions": list(diff.new_collisions),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _append_list(
    *,
    lines: list[str],
    heading: str,
    items: tuple[str, ...],
) -> None:
    """Append a Markdown section listing ``items`` or ``None.``.

    Args:
        lines: Accumulator.
        heading: Section title.
        items: Bullet values.
    """
    lines.extend([f"## {heading}", ""])
    if items:
        lines.extend(f"- `{item}`" for item in items)
    else:
        lines.append("None.")
    lines.append("")
