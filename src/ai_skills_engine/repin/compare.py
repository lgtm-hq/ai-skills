"""Assemble a complete re-pin report from two built catalogs (pure)."""

from collections.abc import Iterable

from ai_skills_engine.provenance.context import origin_locator
from ai_skills_engine.repin import index_diff
from ai_skills_engine.repin.catalog_side import CatalogSide
from ai_skills_engine.repin.change import Change
from ai_skills_engine.repin.drift import Drift
from ai_skills_engine.repin.renames import Migrations
from ai_skills_engine.repin.report import RepinReport
from ai_skills_engine.repin.selector_status import SelectorStatus
from ai_skills_engine.repin.vendor_pin import VendorPin
from ai_skills_engine.semver_advice import recommend_semver


def _collisions(side: CatalogSide) -> set[str]:
    """Select collision diagnostics.

    Args:
        side: Built catalog.

    Returns:
        Collision diagnostic lines.
    """
    return {line for line in side.diagnostics if "collision" in line}


def compare(
    *,
    pin: VendorPin,
    before: CatalogSide,
    after: CatalogSide,
    migrations: Migrations,
    selectors: Iterable[SelectorStatus] = (),
    drift: Iterable[Drift] = (),
    moves: Iterable[Change] = (),
    skill_dirs: tuple[Iterable[str], Iterable[str]] = ((), ()),
    action_required: Iterable[str] = (),
    upstream_moves: bool = False,
) -> RepinReport:
    """Diff the vendor-scoped indexes and attach selector outcomes.

    Args:
        pin: Vendor and revisions.
        before: Baseline catalog.
        after: Re-pinned catalog (may be index-less on failure).
        migrations: Declared migrations.
        selectors: Selector outcomes.
        drift: Path-drift outcomes from the mapping analysis.
        moves: Identical-content paths at a different name.
        skill_dirs: Upstream ``SKILL.md`` directories before and after.
        action_required: Failures.
        upstream_moves: Report declared upstream IDs found at a new path (for
            vendors with their own manifest; mapped moves come from ``drift``).

    Returns:
        Sorted report.
    """
    failed = tuple(dict.fromkeys(action_required))
    collisions = [
        Change(subject=line, kind="new")
        for line in _collisions(after) - _collisions(before)
    ]
    collisions.extend(
        Change(subject=line, kind="resolved")
        for line in _collisions(before) - _collisions(after)
    )
    if failed:
        # Nothing was built at the new revision; never report a bogus delta.
        return RepinReport(
            pin=pin,
            status="failed",
            action_required=failed,
            unapplied_moves=tuple(sorted(set(moves))),
            collisions=tuple(sorted(collisions)),
            selectors=tuple(sorted(set(selectors))),
            drift=tuple(sorted(set(drift))),
        )
    origin = origin_locator(pin.repo)
    old = index_diff.vendor_index(before.index, publisher=pin.publisher, origin=origin)
    new = index_diff.vendor_index(after.index, publisher=pin.publisher, origin=origin)
    capability_lines, applied = index_diff.capability_changes(
        before=old, after=new, renames=migrations
    )
    drift_lines = set(drift)
    if upstream_moves:
        drift_lines.update(
            Drift(
                location="upstream manifest",
                selector=identity,
                old_path=previous,
                status="upstream",
                candidates=(current,),
            )
            for identity, previous, current in index_diff.source_moves(
                before=old, after=new
            )
        )
    unapplied = set(moves)
    unapplied.update(index_diff.identical_moves(before=old, after=new, applied=applied))
    before_dirs, after_dirs = skill_dirs
    uncovered_before = index_diff.uncovered(
        before_dirs, index_diff.covered_paths(old, origin=origin)
    )
    uncovered_after = index_diff.uncovered(
        after_dirs, index_diff.covered_paths(new, origin=origin)
    )
    coverage = [
        Change(
            subject="capabilities",
            kind="count",
            detail=(
                f"{index_diff.capability_count(old)} -> "
                f"{index_diff.capability_count(new)}"
            ),
        )
    ]
    coverage.extend(
        Change(subject=path, kind="newly uncovered")
        for path in uncovered_after - uncovered_before
    )
    coverage.extend(
        Change(subject=path, kind="no longer uncovered")
        for path in uncovered_before - uncovered_after
    )
    return RepinReport(
        pin=pin,
        status="updated",
        semver=recommend_semver(
            index_diff.stable_index(old), index_diff.stable_index(new)
        ),
        capabilities=capability_lines,
        unapplied_moves=tuple(sorted(unapplied)),
        files=index_diff.file_changes(
            before=CatalogSide(index=old, files=before.files),
            after=CatalogSide(index=new, files=after.files),
            applied=applied,
        ),
        resources=index_diff.resource_changes(before=old, after=new),
        lineage=index_diff.lineage_changes(before=old, after=new, applied=applied),
        legal=index_diff.legal_changes(before=old, after=new),
        coverage=tuple(sorted(coverage)),
        collisions=tuple(sorted(collisions)),
        selectors=tuple(sorted(set(selectors))),
        drift=tuple(sorted(drift_lines)),
        digests=index_diff.digest_changes(
            before=old,
            after=new,
            before_artifacts=before.artifact_digests,
            after_artifacts=after.artifact_digests,
        ),
    )
