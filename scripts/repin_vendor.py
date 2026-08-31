#!/usr/bin/env python3
"""Re-pin a vendor SHA, re-bake, and summarize skill/coverage/collision deltas.

Usage:
    uv run python scripts/repin_vendor.py --id mattpocock
    uv run python scripts/repin_vendor.py --all
    uv run python scripts/repin_vendor.py --id mattpocock --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import quote

import bake_vendor_indexes
import bake_vendor_plugins
import manage_vendors
from vendor_registry.registry import load_registry
from vendor_registry.vendor import Vendor
from vendor_registry.vendor_repin_diff import (
    VendorRepinDiff,
    diff_snapshots,
    render_json,
    render_markdown,
)
from vendor_registry.vendor_repin_snapshot import (
    VendorRepinSnapshot,
    snapshot_for_vendor,
)

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_FLOATING_REFS = frozenset({"latest", "HEAD", "head"})
_USER_AGENT = "lgtm-hq-ai-skills-vendor-repin"
_CLI_FAILURES = (
    OSError,
    TypeError,
    ValueError,
    KeyError,
    AttributeError,
    json.JSONDecodeError,
    RuntimeError,
)
ResolveSha = Callable[[Vendor], str]


def _repo_root() -> Path:
    """Return the repository root (parent of ``scripts/``).

    Returns:
        Absolute path to the repository root.
    """
    return Path(__file__).resolve().parents[1]


def list_vendor_ids(*, repo_root: Path) -> tuple[str, ...]:
    """Return registry vendor ids in source order.

    Args:
        repo_root: Repository root containing ``vendors.yaml``.

    Returns:
        Vendor ids.
    """
    vendors = load_registry(registry_path=repo_root / "vendors.yaml")
    return tuple(vendor.id for vendor in vendors)


def resolve_upstream_sha(*, vendor: Vendor) -> str:
    """Resolve the commit SHA for a vendor's consumer-facing pin.

    ``displayRef: latest`` (or a missing / ``HEAD`` ref) tracks the
    repository default branch. Any other ``displayRef`` is resolved as a
    git ref (tag, branch, or commit).

    Args:
        vendor: Registry vendor whose ``repo`` and ``displayRef`` to resolve.

    Returns:
        40-character lowercase hex SHA.

    Raises:
        RuntimeError: If GitHub cannot resolve the ref.
        TypeError: If a commit payload has a non-string sha.
        ValueError: If the resolved object is not a commit SHA.
    """
    owner, name = vendor.repo.split("/", maxsplit=1)
    display_ref = vendor.display_ref
    if display_ref is None or display_ref in _FLOATING_REFS:
        repo_payload = _github_json(path=f"/repos/{owner}/{name}")
        default_branch = repo_payload.get("default_branch")
        if not isinstance(default_branch, str) or not default_branch:
            msg = f"GitHub repo {vendor.repo} has no default_branch"
            raise RuntimeError(msg)
        ref = default_branch
    else:
        ref = display_ref
    commit_payload = _github_json(
        path=f"/repos/{owner}/{name}/commits/{quote(ref, safe='')}",
    )
    sha = commit_payload.get("sha")
    if not isinstance(sha, str):
        msg = f"GitHub commit {vendor.repo}@{ref} is missing sha"
        raise TypeError(msg)
    normalized = sha.strip().lower()
    if _SHA_PATTERN.fullmatch(normalized) is None:
        msg = f"GitHub commit {vendor.repo}@{ref} returned invalid sha {sha!r}"
        raise ValueError(msg)
    return normalized


def _github_json(*, path: str) -> dict[str, object]:
    """GET a GitHub API JSON object.

    Args:
        path: API path beginning with ``/``.

    Returns:
        Parsed object payload.

    Raises:
        TypeError: If the response is not a JSON object.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = bake_vendor_plugins._http_get_bytes(
        host="api.github.com",
        path=path,
        headers=headers,
    )
    parsed: object = json.loads(payload.decode("utf-8"))
    if not isinstance(parsed, dict):
        msg = f"GitHub {path} did not return a JSON object"
        raise TypeError(msg)
    return parsed


def _snapshot_vendor(
    *,
    repo_root: Path,
    vendor: Vendor,
    vendor_trees: Mapping[str, Path] | None,
) -> VendorRepinSnapshot:
    """Bake the current registry and snapshot one vendor.

    Args:
        repo_root: Repository root.
        vendor: Vendor whose slices to project.
        vendor_trees: Optional local trees keyed by vendor id.

    Returns:
        Snapshot including the global collision report.
    """
    (
        results,
        skipped_by_vendor,
        ingested_counts,
        _fetched,
        skill_collisions,
        agent_collisions,
        skill_digests,
    ) = bake_vendor_plugins.collect_bake(
        repo_root=repo_root,
        vendor_trees=vendor_trees,
        install=True,
    )
    return snapshot_for_vendor(
        vendor=vendor,
        results=results,
        skipped_by_vendor=skipped_by_vendor,
        ingested_counts=ingested_counts,
        skill_collisions=skill_collisions,
        agent_collisions=agent_collisions,
        skill_digests=skill_digests,
    )


def _reload_vendor(*, repo_root: Path, vendor_id: str) -> Vendor:
    """Load one vendor after the registry file may have changed.

    Args:
        repo_root: Repository root.
        vendor_id: Vendor slug.

    Returns:
        Matching vendor record.

    Raises:
        ValueError: If the vendor id is unknown.
    """
    vendors = load_registry(registry_path=repo_root / "vendors.yaml")
    vendor = next((item for item in vendors if item.id == vendor_id), None)
    if vendor is None:
        msg = f"Unknown vendor id: {vendor_id}"
        raise ValueError(msg)
    return vendor


def _vendor_from_registry_text(*, text: str, vendor_id: str) -> Vendor:
    """Load one vendor from a ``vendors.yaml`` snapshot without touching disk.

    Args:
        text: Registry file contents.
        vendor_id: Vendor slug.

    Returns:
        Matching vendor record.

    Raises:
        ValueError: If the vendor id is unknown.
        TypeError: If the registry fails type validation.
    """
    with tempfile.TemporaryDirectory(prefix="vendor-repin-") as tmp:
        path = Path(tmp) / "vendors.yaml"
        path.write_text(text, encoding="utf-8")
        vendors = load_registry(registry_path=path)
    vendor = next((item for item in vendors if item.id == vendor_id), None)
    if vendor is None:
        msg = f"Unknown vendor id: {vendor_id}"
        raise ValueError(msg)
    return vendor


def _registry_text_at_ref(*, repo_root: Path, git_ref: str) -> str:
    """Return ``vendors.yaml`` from ``git_ref``.

    Args:
        repo_root: Repository root.
        git_ref: Commit SHA or other git revision.

    Returns:
        File contents at that revision.

    Raises:
        ValueError: If ``git_ref`` is empty or looks like an option/path.
        RuntimeError: If git cannot show the file.
    """
    if not git_ref or git_ref.startswith("-") or ":" in git_ref:
        msg = f"invalid baseline-ref {git_ref!r}"
        raise ValueError(msg)
    try:
        return subprocess.check_output(  # nosec B603 - fixed git argv; ref validated
            ["git", "show", f"{git_ref}:vendors.yaml"],
            cwd=repo_root,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        msg = f"could not read vendors.yaml at {git_ref}: {error}"
        raise RuntimeError(msg) from error


def repin_vendor(
    *,
    repo_root: Path,
    vendor_id: str,
    vendor_trees: Mapping[str, Path] | None = None,
    resolve_sha: ResolveSha | None = None,
    baseline_ref: str | None = None,
    baseline_registry_text: str | None = None,
) -> VendorRepinDiff:
    """Bump one vendor pin, refresh derived artifacts, and diff bakes.

    Unresolved collisions fail closed: the pin SHA stays updated so a
    re-pin PR can add ``renameSkills``, and the returned diff includes
    the collision lines.

    ``baseline_ref`` / ``baseline_registry_text`` select the *full*
    registry used for the ``before`` snapshot (main's ``vendors.yaml``
    when updating an existing re-pin PR). Resetting only the SHA would
    bake main's pin against branch-only ``renameSkills`` and can raise
    unused-rename errors or omit the real main-to-branch delta.

    Args:
        repo_root: Repository root containing ``vendors.yaml``.
        vendor_id: Vendor slug to re-pin.
        vendor_trees: Optional local trees keyed by vendor id.
        resolve_sha: Optional SHA resolver (tests inject a stub).
        baseline_ref: Git revision whose ``vendors.yaml`` is the summary
            baseline. Mutually exclusive with ``baseline_registry_text``.
        baseline_registry_text: Registry snapshot used as ``before``.
            Tests inject this instead of a git ref.

    Returns:
        Snapshot delta. ``unchanged`` is true when the pin already
        matches upstream.

    Raises:
        ValueError: If the vendor id is unknown or both baseline inputs
            are set.
        RuntimeError: If GitHub cannot resolve the upstream ref or git
            cannot read the baseline registry.
        TypeError: If a GitHub payload is the wrong type.
    """
    if baseline_ref is not None and baseline_registry_text is not None:
        msg = "baseline_ref and baseline_registry_text are mutually exclusive"
        raise ValueError(msg)
    vendor = _reload_vendor(repo_root=repo_root, vendor_id=vendor_id)
    registry_path = repo_root / "vendors.yaml"
    working_text = registry_path.read_text(encoding="utf-8")
    if baseline_ref is not None:
        baseline_text = _registry_text_at_ref(
            repo_root=repo_root,
            git_ref=baseline_ref,
        )
    elif baseline_registry_text is not None:
        baseline_text = baseline_registry_text
    else:
        baseline_text = working_text
    if baseline_text != working_text:
        _vendor_from_registry_text(text=baseline_text, vendor_id=vendor_id)
    if resolve_sha is not None:
        new_sha = resolve_sha(vendor)
    else:
        new_sha = resolve_upstream_sha(vendor=vendor)
    if new_sha == vendor.sha and baseline_text == working_text:
        before = _snapshot_vendor(
            repo_root=repo_root,
            vendor=vendor,
            vendor_trees=vendor_trees,
        )
        after = VendorRepinSnapshot(
            vendor_id=before.vendor_id,
            sha=before.sha,
            explode_names=before.explode_names,
            skipped=before.skipped,
            ingested_count=before.ingested_count,
            collisions=before.collisions,
            skill_digests=before.skill_digests,
        )
        return diff_snapshots(before=before, after=after)
    artifact_paths = manage_vendors._generated_artifact_paths(repo_root=repo_root)
    snapshot, directories = manage_vendors._snapshot_artifacts(paths=artifact_paths)
    completed = False
    try:
        if baseline_text != working_text:
            registry_path.write_text(baseline_text, encoding="utf-8")
            load_registry(registry_path=registry_path)
        before = _snapshot_vendor(
            repo_root=repo_root,
            vendor=_reload_vendor(repo_root=repo_root, vendor_id=vendor_id),
            vendor_trees=vendor_trees,
        )
        registry_path.write_text(working_text, encoding="utf-8")
        if new_sha != vendor.sha:
            manage_vendors.set_sha(
                repo_root=repo_root,
                vendor_id=vendor_id,
                sha=new_sha,
            )
        bake_vendor_indexes.bake(repo_root=repo_root)
        after_vendor = _reload_vendor(repo_root=repo_root, vendor_id=vendor_id)
        after = _snapshot_vendor(
            repo_root=repo_root,
            vendor=after_vendor,
            vendor_trees=vendor_trees,
        )
        manage_vendors._sync_artifacts(repo_root=repo_root, check_only=False)
        completed = True
        return diff_snapshots(before=before, after=after)
    finally:
        if not completed:
            registry_path.write_text(working_text, encoding="utf-8")
            manage_vendors._restore_artifacts(
                paths=artifact_paths,
                snapshot=snapshot,
                directories=directories,
            )


def _emit(
    *,
    diff: VendorRepinDiff,
    display_ref: str | None,
    as_json: bool,
    summary_path: Path | None,
) -> None:
    """Write human and optional machine summaries.

    Args:
        diff: Snapshot delta.
        display_ref: Registry ``displayRef``.
        as_json: When true, print JSON instead of Markdown.
        summary_path: Optional Markdown file for a PR body.
    """
    markdown = render_markdown(diff=diff, display_ref=display_ref)
    if summary_path is not None:
        summary_path.write_text(markdown, encoding="utf-8")
    if as_json:
        print(render_json(diff=diff, display_ref=display_ref), end="")
        return
    print(markdown, end="")


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and re-pin one or every vendor.

    Args:
        argv: CLI arguments, defaulting to process arguments.

    Returns:
        ``0`` when every targeted pin is current or bumped cleanly.
        ``1`` when a bump introduces unresolved collisions or a
        resolution/bake error occurs.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    exclusive = parser.add_mutually_exclusive_group(required=False)
    exclusive.add_argument(
        "--id",
        dest="vendor_id",
        help="Vendor id to re-pin",
    )
    exclusive.add_argument(
        "--all",
        action="store_true",
        help="Re-pin every vendor in vendors.yaml",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the machine-readable summary to stdout",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=None,
        help="Write the Markdown summary to this path (PR body)",
    )
    parser.add_argument(
        "--baseline-ref",
        dest="baseline_ref",
        default=None,
        help="Git revision whose vendors.yaml is the summary baseline",
    )
    parser.add_argument(
        "--list-json",
        action="store_true",
        help="Print vendor ids as a JSON array and exit",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root override (default: parent of scripts/)",
    )
    args = parser.parse_args(argv)
    if not args.list_json and args.vendor_id is None and not args.all:
        parser.error("one of --id, --all, or --list-json is required")
    if args.all and (args.json or args.summary_path is not None):
        parser.error("--json and --summary-path require --id")
    if args.baseline_ref is not None and args.vendor_id is None:
        parser.error("--baseline-ref requires --id")
    repo_root = args.repo_root if args.repo_root is not None else _repo_root()
    try:
        vendor_ids = list_vendor_ids(repo_root=repo_root)
        if args.vendor_id is not None and args.vendor_id not in vendor_ids:
            msg = f"Unknown vendor id: {args.vendor_id}"
            raise ValueError(msg)
        selected = vendor_ids if args.vendor_id is None else (args.vendor_id,)
        if args.list_json:
            print(json.dumps(list(selected), separators=(",", ":")))
            return 0
        failed = False
        for vendor_id in selected:
            diff = repin_vendor(
                repo_root=repo_root,
                vendor_id=vendor_id,
                baseline_ref=args.baseline_ref,
            )
            vendor = _reload_vendor(repo_root=repo_root, vendor_id=vendor_id)
            if diff.new_collisions and not diff.unchanged:
                failed = True
            if args.json or args.summary_path is not None:
                _emit(
                    diff=diff,
                    display_ref=vendor.display_ref,
                    as_json=args.json,
                    summary_path=args.summary_path,
                )
            else:
                print(
                    render_markdown(
                        diff=diff,
                        display_ref=vendor.display_ref,
                    ),
                    end="",
                )
        return 1 if failed else 0
    except _CLI_FAILURES as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
