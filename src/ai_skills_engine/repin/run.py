"""Re-pin one vendor on the lock/artifact model inside one file transaction.

Steps: build the baseline catalog, move the pin, apply declared renames,
reconcile uniquely moved mapping paths, count every selector, build the new
catalog, write ``ai-skills.lock`` and the compatibility outputs, then diff the
two artifact indexes. Any failure restores every file; the returned report then
carries an "Action required" section instead of a delta.
"""

import contextlib
import re
import sys
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import ai_skills_engine.bake.vendor_indexes as bake_vendor_indexes
import ai_skills_engine.vendors.manage as manage_vendors
from ai_skills_engine.commands.mapping_scaffold import require_accepted
from ai_skills_engine.lockfile import LOCK_FILENAME, loads, write_lock
from ai_skills_engine.lockmodel.locked_vendor import LockedVendor
from ai_skills_engine.manifest import legacy
from ai_skills_engine.manifest.edit import patch_document
from ai_skills_engine.manifest.load import load_manifest, read_document
from ai_skills_engine.manifest.transaction import restore_files, snapshot_files
from ai_skills_engine.registry.ingest_checks import safe_diagnostic
from ai_skills_engine.registry.vendor import Vendor
from ai_skills_engine.repin import catalog
from ai_skills_engine.repin.baseline import Baseline
from ai_skills_engine.repin.catalog_side import CatalogSide
from ai_skills_engine.repin.compare import compare
from ai_skills_engine.repin.mapping_selectors import analyze_mapping
from ai_skills_engine.repin.renames import (
    declared_migrations,
    rewrite_filters,
    rewrite_mapping,
)
from ai_skills_engine.repin.report import RepinReport
from ai_skills_engine.repin.selector_plan import SelectorPlan
from ai_skills_engine.repin.selector_status import SelectorStatus
from ai_skills_engine.repin.source_tree import SourceTree
from ai_skills_engine.repin.vendor_pin import VendorPin
from ai_skills_engine.source_cache import Fetcher

MANIFEST = "ai-skills.yaml"
_SHA = re.compile(r"[0-9a-f]{40}")
type Resolver = Callable[[Vendor], str]
type DeclinedLookup = Callable[[str, str], int | None]


class _Failed(Exception):
    """Carry a failed report through the transaction's restore path.

    Args:
        report: Failed re-pin report.
    """

    def __init__(self, report: RepinReport) -> None:
        super().__init__("re-pin failed")
        self.report = report


def vendor_record(entry: Mapping[str, Any]) -> Vendor:
    """Describe a manifest vendor for upstream resolution.

    Args:
        entry: Manifest vendor declaration.

    Returns:
        Registry vendor with the pin, branch and display ref.
    """
    return Vendor(
        id=entry["id"],
        repo=entry["repo"],
        sha=entry["sha"],
        skill_roots=(),
        license=entry.get("license", ""),
        homepage=entry.get("homepage", ""),
        display_ref=entry.get("displayRef"),
        branch=entry.get("branch"),
    )


def find_vendor(document: Mapping[str, Any], vendor_id: str) -> dict[str, Any] | None:
    """Find a top-level vendor declaration.

    Args:
        document: Manifest mapping.
        vendor_id: Vendor alias.

    Returns:
        The declaration, or None.
    """
    return next(
        (item for item in document.get("vendors", []) if item["id"] == vendor_id),
        None,
    )


def _document(*, text: str, scratch: Path) -> dict[str, Any]:
    """Parse manifest text with the manifest's own guarded loader.

    Args:
        text: Manifest YAML.
        scratch: Private directory.

    Returns:
        Parsed mapping.
    """
    path = scratch / "baseline" / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return read_document(path)


def _locked(data: bytes | None) -> dict[str, LockedVendor]:
    """Read locked vendor records.

    Args:
        data: Lock bytes, None when absent.

    Returns:
        Locked vendors by alias.
    """
    return {} if data is None else {item.id: item for item in loads(data).vendors}


def _publish_manifest(*, path: Path, original: str, data: dict[str, Any]) -> None:
    """Losslessly write manifest values and validate before anything else.

    The writer quotes parser-divergent ``sha``/``branch`` spellings; validation
    rejects any remaining ambiguous plain scalar before compatibility output.

    Args:
        path: Manifest path.
        original: Manifest text supplying comments and layout.
        data: Authoritative values.
    """
    updated = patch_document(text=original, data=data)
    if updated != path.read_text(encoding="utf-8"):
        path.write_text(updated, encoding="utf-8")
    load_manifest(path)


def _target(
    *,
    entry: Mapping[str, Any],
    revision: str | None,
    keep_sha: bool,
    resolve: Resolver | None,
) -> str:
    """Choose the new revision.

    Args:
        entry: Current vendor declaration.
        revision: Explicit revision.
        keep_sha: Keep the declared pin (Renovate already moved it).
        resolve: Upstream resolver.

    Returns:
        40-hex revision.

    Raises:
        ValueError: If no resolver is available or the revision is malformed.
    """
    if keep_sha:
        target = str(entry["sha"])
    elif revision is not None:
        target = revision
    elif resolve is not None:
        target = resolve(vendor_record(entry))
    else:
        raise ValueError("repin needs --revision, --keep-sha or an upstream resolver")
    if _SHA.fullmatch(target) is None:
        raise ValueError(f"Revision must be a lowercase 40-hex commit SHA: {target!r}")
    return target


def _merge_statuses(
    renamed: tuple[SelectorStatus, ...], counted: tuple[SelectorStatus, ...]
) -> tuple[SelectorStatus, ...]:
    """Combine declared-rename rewrites with their match counts.

    Args:
        renamed: Selectors rewritten by a declared migration.
        counted: Counted selectors after all rewrites.

    Returns:
        Counted selectors, marked renamed where a declaration applied.
    """
    details = {(item.location, item.selector): item.detail for item in renamed}
    return tuple(
        (
            replace(
                item,
                status="renamed" if item.status == "ok" else item.status,
                detail=details[(item.location, item.selector)],
            )
            if (item.location, item.selector) in details
            else item
        )
        for item in counted
    )


def _publish_compatibility(root: Path) -> None:
    """Refresh the legacy registry, vendor indexes and npm data from the manifest.

    Only repositories that already maintain ``vendors.yaml`` publish these
    compatibility outputs; a plain consumer only owns its manifest and lock.

    Args:
        root: Repository root.
    """
    if not (root / "vendors.yaml").is_file():
        return
    # Keep stdout for the report (``--json`` must stay parseable).
    with contextlib.redirect_stdout(sys.stderr):
        legacy.write_legacy(root)
        bake_vendor_indexes.bake(repo_root=root)
        manage_vendors._sync_artifacts(repo_root=root, check_only=False)


def _repin(
    *,
    root: Path,
    scratch: Path,
    pin: VendorPin,
    document: dict[str, Any],
    working_text: str,
    working_lock: bytes | None,
    baseline: Baseline,
    supplied: Mapping[str, Path] | None,
    fetcher: Fetcher | None,
    rewrite_manifest: bool,
) -> RepinReport:
    """Run the build/diff steps; the caller owns rollback.

    Args:
        root: Repository root.
        scratch: Private directory.
        pin: Vendor and revisions (publisher filled in here).
        document: Working manifest.
        working_text: Working manifest text.
        working_lock: Working lock bytes.
        baseline: Baseline declarations.
        supplied: Explicit offline snapshots for the new revision.
        fetcher: Acquisition override.
        rewrite_manifest: Apply reconciled paths and declared renames; when
            False (automation that cannot publish the manifest) each required
            rewrite becomes an action item instead.

    Returns:
        Report; failed reports must be rolled back by the caller.

    Raises:
        ValueError: If the baseline catalog itself does not build.
    """
    manifest = root / MANIFEST
    if baseline.manifest_text != working_text:
        manifest.write_text(baseline.manifest_text, encoding="utf-8")
    before_roots, before_vendors = catalog.materialize(
        root=root,
        scratch=scratch / "before-sources",
        locked=_locked(baseline.lock_bytes),
        fetcher=fetcher,
    )
    before_inputs = catalog.observe(root=root, roots=before_roots)
    errors = catalog.selection_errors(before_inputs[1])
    if errors:
        raise ValueError("Baseline catalog does not build:\n" + "\n".join(errors))
    before, _ = catalog.build(
        root=root,
        roots=before_roots,
        vendors=before_vendors,
        inputs=before_inputs,
        destination=scratch / "before",
    )
    manifest.write_text(working_text, encoding="utf-8")
    data = deepcopy(document)
    entry = find_vendor(data, pin.id)
    if entry is None:
        raise ValueError(f"Unknown vendor id: {pin.id}")
    entry["sha"] = pin.new_sha
    _publish_manifest(path=manifest, original=working_text, data=data)
    after_roots, after_vendors = catalog.materialize(
        root=root,
        scratch=scratch / "after-sources",
        locked=_locked(working_lock),
        supplied=supplied,
        fetcher=fetcher,
    )
    new_tree, old_tree = after_roots[pin.id], before_roots.get(pin.id)
    upstream = new_tree / MANIFEST
    publisher = (
        str(read_document(upstream)["publisher"]["id"])
        if upstream.is_file()
        else pin.id
    )
    pin = replace(pin, publisher=publisher)
    migrations = declared_migrations(document=data, tree=new_tree, publisher=publisher)
    renamed_entry, renamed = rewrite_mapping(
        entry=entry, vendor=pin.id, migrations=migrations
    )
    new_source = SourceTree(new_tree)
    old_source = SourceTree(old_tree) if old_tree is not None else None
    plan = (
        SelectorPlan(entry=renamed_entry)
        if upstream.is_file()
        else analyze_mapping(entry=renamed_entry, old=old_source, new=new_source)
    )
    failures = list(plan.failures)
    statuses = list(_merge_statuses(renamed, plan.statuses))
    data["vendors"] = [
        plan.entry if item["id"] == pin.id else item for item in data["vendors"]
    ]
    _publish_manifest(path=manifest, original=working_text, data=data)
    after = CatalogSide(index={})
    lock = None
    if not failures:
        try:
            inventory, selection = catalog.observe(root=root, roots=after_roots)
        except (TypeError, ValueError) as error:
            failures.append(safe_diagnostic(str(error)))
        else:
            filtered, filters = rewrite_filters(
                entry=plan.entry,
                migrations=migrations,
                identities=catalog.identities(inventory),
            )
            statuses.extend(filters)
            dead = [
                f"Dead selector {item.location}: {item.selector!r} matches nothing "
                "at the new revision"
                for item in filters
                if item.status == "dead"
            ]
            failures.extend(dead)
            if filtered != plan.entry:
                data["vendors"] = [
                    filtered if item["id"] == pin.id else item
                    for item in data["vendors"]
                ]
                _publish_manifest(path=manifest, original=working_text, data=data)
                inventory, selection = catalog.observe(root=root, roots=after_roots)
            errors = catalog.selection_errors(selection)
            after = CatalogSide(index={}, diagnostics=errors)
            # A named dead selector already explains the resolver's unmatched error.
            failures.extend(
                line for line in errors if not (dead and "selector-unmatched" in line)
            )
            if not rewrite_manifest:
                failures.extend(
                    f"Manifest edit required (automation does not publish "
                    f"ai-skills.yaml): {item.location} {item.selector!r}: "
                    f"{item.detail}; run `ai-skills-engine repin --vendor {pin.id} "
                    "--keep-sha --baseline-ref <base>` on this branch"
                    for item in statuses
                    if item.status in {"reconciled", "renamed"}
                )
            if not failures:
                after, lock = catalog.build(
                    root=root,
                    roots=after_roots,
                    vendors=after_vendors,
                    inputs=(inventory, selection),
                    destination=scratch / "after",
                )
    report = compare(
        pin=pin,
        before=replace(before, diagnostics=catalog.selection_errors(before_inputs[1])),
        after=after,
        migrations=migrations,
        selectors=statuses,
        drift=plan.drifts,
        moves=plan.moves,
        skill_dirs=(
            old_source.skill_directories() if old_source is not None else (),
            new_source.skill_directories(),
        ),
        action_required=failures,
        upstream_moves=upstream.is_file(),
    )
    if lock is not None and not report.failed:
        write_lock(path=root / LOCK_FILENAME, lock=lock)
        _publish_compatibility(root)
    return report


def repin_vendor(
    *,
    root: Path,
    vendor_id: str,
    revision: str | None = None,
    keep_sha: bool = False,
    baseline: Baseline | None = None,
    supplied: Mapping[str, Path] | None = None,
    fetcher: Fetcher | None = None,
    resolve: Resolver | None = None,
    declined: DeclinedLookup | None = None,
    rewrite_manifest: bool = True,
) -> RepinReport:
    """Re-pin one vendor and report the bake diff.

    Args:
        root: Repository root containing ``ai-skills.yaml``.
        vendor_id: Top-level vendor alias.
        revision: Explicit new revision.
        keep_sha: Summarize the declared pin (Renovate already moved it).
        baseline: Base-branch declarations; defaults to the working files.
        supplied: Explicit offline snapshots of the new revision by alias.
        fetcher: Source acquisition override.
        resolve: Upstream revision resolver.
        declined: Lookup returning a PR that declined ``(vendor, revision)``.
        rewrite_manifest: Apply reconciled paths and declared renames to
            ``ai-skills.yaml``; False reports them as action items instead.

    Returns:
        The report. ``failed`` reports leave every file exactly as it was.

    Raises:
        ValueError: For an unknown vendor, a missing manifest or invalid input.
        RuntimeError: If rollback could not restore a file.
    """
    manifest = root / MANIFEST
    if not manifest.is_file():
        raise ValueError(
            "repin requires ai-skills.yaml; run `ai-skills-engine manifest migrate`"
        )
    working_text = manifest.read_text(encoding="utf-8")
    load_manifest(manifest)
    document = read_document(manifest)
    # Like ``lock``: never lock consumer-asserted identities nobody reviewed.
    require_accepted(document)
    entry = find_vendor(document, vendor_id)
    if entry is None:
        raise ValueError(f"Unknown vendor id: {vendor_id}")
    lock_path = root / LOCK_FILENAME
    working_lock = lock_path.read_bytes() if lock_path.is_file() else None
    base = baseline or Baseline(manifest_text=working_text, lock_bytes=working_lock)
    with TemporaryDirectory(prefix="ai-skills-repin-") as temporary:
        # Resolve a symlinked TMPDIR (macOS /var) before artifact output checks.
        scratch = Path(temporary).resolve()
        old_entry = find_vendor(
            _document(text=base.manifest_text, scratch=scratch), vendor_id
        )
        new_sha = _target(
            entry=entry, revision=revision, keep_sha=keep_sha, resolve=resolve
        )
        pin = VendorPin(
            id=vendor_id,
            repo=entry["repo"],
            publisher=vendor_id,
            display_ref=entry.get("displayRef") or "latest",
            old_sha=None if old_entry is None else old_entry["sha"],
            new_sha=new_sha,
        )
        if declined is not None and not keep_sha and new_sha != entry["sha"]:
            number = declined(vendor_id, new_sha)
            if number is not None:
                print(
                    f"repin: {vendor_id}: skipping revision {new_sha}; it was "
                    f"declined in closed PR #{number}",
                    file=sys.stderr,
                )
                return RepinReport(pin=pin, status="declined")
        if old_entry == entry and new_sha == entry["sha"]:
            return RepinReport(pin=pin, status="unchanged")
        paths = (
            manifest,
            lock_path,
            root / "vendors.yaml",
            root / "bundles.yaml",
        )
        originals = snapshot_files(paths)
        artifact_paths = manage_vendors._generated_artifact_paths(repo_root=root)
        snapshot, directories = manage_vendors._snapshot_artifacts(paths=artifact_paths)
        try:
            report = _repin(
                root=root,
                scratch=scratch,
                pin=pin,
                document=document,
                working_text=working_text,
                working_lock=working_lock,
                baseline=base,
                supplied=supplied,
                fetcher=fetcher,
                rewrite_manifest=rewrite_manifest,
            )
            if report.failed:
                raise _Failed(report)
            return report
        except _Failed as failure:
            restore_files(originals=originals, error=failure)
            manage_vendors._restore_artifacts(
                paths=artifact_paths,
                snapshot=snapshot,
                directories=directories,
                error=failure,
            )
            if getattr(failure, "__notes__", None):
                error = RuntimeError("re-pin rollback was incomplete")
                for note in failure.__notes__:
                    error.add_note(note)
                raise error from failure
            return failure.report
        except BaseException as error:
            restore_files(originals=originals, error=error)
            manage_vendors._restore_artifacts(
                paths=artifact_paths,
                snapshot=snapshot,
                directories=directories,
                error=error,
            )
            raise
