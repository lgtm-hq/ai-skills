#!/usr/bin/env python3
"""Re-pin vendors on the lock/artifact model with deterministic bake-diff bodies.

Usage:
    uv run ai-skills-engine repin --vendor anthropics --summary-path body.md [--json]
    uv run ai-skills-engine repin --all
    uv run ai-skills-engine repin --all --keep-sha --baseline-ref BASE

Each re-pin moves the pin in ``ai-skills.yaml``, resolves ``ai-skills.lock``,
builds the artifacts and diffs the old and new artifact indexes. Failures (dead
selectors, ambiguous or missing path drift, collisions) restore every file and
still emit a body with an "Action required" section and exit 1.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess  # nosec B404 - fixed git argv list, no shell
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

import ai_skills_engine.bake.vendor_plugins as bake_vendor_plugins
from ai_skills_engine.inventory.cli import vendor_roots
from ai_skills_engine.lockfile import LOCK_FILENAME
from ai_skills_engine.manifest import legacy
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.paths import resolve_repo_root
from ai_skills_engine.registry.ingest_checks import safe_diagnostic
from ai_skills_engine.registry.registry import load_registry
from ai_skills_engine.registry.vendor import Vendor
from ai_skills_engine.repin.baseline import Baseline
from ai_skills_engine.repin.declined import declined_pr
from ai_skills_engine.repin.render import render_markdown, to_json
from ai_skills_engine.repin.report import RepinReport
from ai_skills_engine.repin.run import MANIFEST, find_vendor, repin_vendor
from ai_skills_engine.repin.vendor_pin import VendorPin

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


def _selection_vendors(*, repo_root: Path) -> tuple[Vendor, ...]:
    """Read authoritative declarations without publishing during CLI selection.

    Args:
        repo_root: Repository containing a manifest or legacy registry.

    Returns:
        Validated vendors in source order.
    """
    if (repo_root / "ai-skills.yaml").is_file():
        rendered = legacy.render_legacy(repo_root)
        return _vendors_from_registry_text(
            text=rendered[repo_root / "vendors.yaml"].decode("utf-8"),
        )
    return load_registry(registry_path=repo_root / "vendors.yaml")


def list_vendor_ids(*, repo_root: Path) -> tuple[str, ...]:
    """Return authoritative vendor ids in source order without publication.

    Args:
        repo_root: Repository root containing a manifest or ``vendors.yaml``.

    Returns:
        Vendor ids.
    """
    vendors = _selection_vendors(repo_root=repo_root)
    return tuple(vendor.id for vendor in vendors)


def resolve_upstream_sha(*, vendor: Vendor) -> str:
    """Resolve the commit SHA for a vendor's consumer-facing pin.

    An explicit ``branch`` takes precedence. Otherwise ``displayRef: latest``
    (or a missing / ``HEAD`` ref) tracks the repository default branch;
    other display refs resolve as a tag, branch, or commit.

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
    if vendor.branch is not None:
        ref = f"refs/heads/{vendor.branch}"
    elif display_ref is None or display_ref in _FLOATING_REFS:
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


def _vendors_from_registry_text(*, text: str) -> tuple[Vendor, ...]:
    """Load registry text through the real reader in private scratch space.

    Args:
        text: Registry file contents.

    Returns:
        Validated vendors in source order.

    Raises:
        TypeError: If the registry fails type validation.
    """
    with tempfile.TemporaryDirectory(prefix="vendor-repin-") as tmp:
        path = Path(tmp) / "vendors.yaml"
        path.write_text(text, encoding="utf-8")
        return load_registry(registry_path=path)


def _text_at_ref(*, repo_root: Path, git_ref: str, name: str) -> str | None:
    """Return a tracked file at ``git_ref``.

    Args:
        repo_root: Repository root.
        git_ref: Commit SHA or other git revision.
        name: Repository-relative file name.

    Returns:
        File contents, or None when the revision has no such file.

    Raises:
        ValueError: If ``git_ref`` is empty or looks like an option/path.
        RuntimeError: If git cannot resolve the revision.
    """
    if not git_ref or git_ref.startswith("-") or ":" in git_ref:
        msg = f"invalid baseline-ref {git_ref!r}"
        raise ValueError(msg)
    try:
        subprocess.check_output(  # nosec B603 B607 - fixed git argv
            ["git", "rev-parse", "--verify", "--quiet", f"{git_ref}^{{commit}}"],
            cwd=repo_root,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        msg = f"could not resolve baseline-ref {git_ref}: {error}"
        raise RuntimeError(msg) from error
    try:
        # Bytes, then UTF-8: text mode would translate CRLF and break byte
        # equality with the committed manifest and lock.
        return subprocess.check_output(  # nosec B603 B607 - fixed git argv
            ["git", "show", f"{git_ref}:{name}"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8")
    except subprocess.CalledProcessError:
        return None


def baseline_at_ref(*, repo_root: Path, git_ref: str) -> Baseline:
    """Read the manifest and lock committed at the baseline revision.

    Args:
        repo_root: Repository root.
        git_ref: Base-branch revision (for example the merge base).

    Returns:
        Baseline declarations.

    Raises:
        RuntimeError: If the revision has no ``ai-skills.yaml``.
    """
    manifest = _text_at_ref(repo_root=repo_root, git_ref=git_ref, name=MANIFEST)
    if manifest is None:
        msg = f"could not read {MANIFEST} at {git_ref}"
        raise RuntimeError(msg)
    lock = _text_at_ref(repo_root=repo_root, git_ref=git_ref, name=LOCK_FILENAME)
    return Baseline(
        manifest_text=manifest,
        lock_bytes=None if lock is None else lock.encode("utf-8"),
    )


def _failure_report(*, entry: dict[str, object], error: BaseException) -> RepinReport:
    """Describe an exception as a failed re-pin so a body is always emitted.

    Args:
        entry: Manifest vendor declaration.
        error: Failure, including any rollback notes.

    Returns:
        Failed report naming the pinned revision.
    """
    messages = [safe_diagnostic(str(error))]
    messages.extend(
        safe_diagnostic(str(note)) for note in getattr(error, "__notes__", ())
    )
    return RepinReport(
        pin=VendorPin(
            id=str(entry["id"]),
            repo=str(entry["repo"]),
            publisher=str(entry["id"]),
            display_ref=str(entry.get("displayRef") or "latest"),
            old_sha=str(entry["sha"]),
            new_sha=str(entry["sha"]),
        ),
        status="failed",
        action_required=tuple(messages),
    )


def _parser() -> argparse.ArgumentParser:
    """Define the command line.

    Returns:
        Argument parser.
    """
    parser = argparse.ArgumentParser(
        prog="ai-skills-engine repin",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    exclusive = parser.add_mutually_exclusive_group(required=False)
    exclusive.add_argument("--vendor", "--id", dest="vendor_id", help="Vendor id")
    exclusive.add_argument("--all", action="store_true", help="Re-pin every vendor")
    parser.add_argument(
        "--revision",
        help="Explicit new 40-hex revision instead of resolving upstream",
    )
    parser.add_argument(
        "--keep-sha",
        action="store_true",
        help="Summarize the declared pin instead of resolving a newer revision",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON (an object for --vendor, an array for --all)",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=None,
        help="Write the combined Markdown PR body to this path",
    )
    parser.add_argument(
        "--baseline-ref",
        default=None,
        help="Git revision whose ai-skills.yaml and ai-skills.lock are the baseline",
    )
    parser.add_argument(
        "--vendor-root",
        "--vendor-tree",
        action="append",
        default=[],
        metavar="ID=PATH",
        help="Local snapshot of the new revision instead of fetching",
    )
    parser.add_argument(
        "--skip-declined",
        action="store_true",
        help=(
            "Skip a revision declined in a closed, unmerged re-pin PR (uses gh); "
            "a no-op with --keep-sha or when the revision equals the current pin"
        ),
    )
    parser.add_argument(
        "--no-manifest-rewrite",
        action="store_true",
        help=(
            "Report reconciled paths and declared renames as action items "
            "instead of editing ai-skills.yaml (automation cannot publish it)"
        ),
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
        help="Repository root override (default: discover from current directory)",
    )
    return parser


def _resolve(vendor: Vendor) -> str:
    """Resolve upstream through GitHub.

    Args:
        vendor: Vendor record.

    Returns:
        Resolved revision.
    """
    return resolve_upstream_sha(vendor=vendor)


def _declined(vendor: str, revision: str) -> int | None:
    """Look up a declined revision through ``gh``.

    Args:
        vendor: Vendor alias.
        revision: Candidate revision.

    Returns:
        Declining PR number, or None.
    """
    return declined_pr(vendor=vendor, revision=revision)


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and re-pin one or every vendor.

    Args:
        argv: CLI arguments, defaulting to process arguments.

    Returns:
        ``0`` when every targeted vendor is current, re-pinned or declined;
        ``1`` when any re-pin requires action or a selection error occurs.
    """
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.list_json and args.vendor_id is None and not args.all:
        parser.error("one of --vendor, --all, or --list-json is required")
    if args.revision is not None and (args.all or args.keep_sha):
        parser.error("--revision requires --vendor and excludes --keep-sha")
    repo_root = resolve_repo_root(override=args.repo_root, parser=parser)
    try:
        if args.list_json:
            ids = list_vendor_ids(repo_root=repo_root)
            if args.vendor_id is not None and args.vendor_id not in ids:
                raise ValueError(f"Unknown vendor id: {args.vendor_id}")
            selected_ids = ids if args.vendor_id is None else (args.vendor_id,)
            print(json.dumps(list(selected_ids), separators=(",", ":")))
            return 0
        manifest = repo_root / MANIFEST
        if not manifest.is_file():
            raise ValueError(
                "repin requires ai-skills.yaml; run "
                "`ai-skills-engine manifest migrate`"
            )
        document = read_document(manifest)
        entries = {item["id"]: item for item in document.get("vendors", [])}
        if args.vendor_id is not None and args.vendor_id not in entries:
            raise ValueError(f"Unknown vendor id: {args.vendor_id}")
        baseline = (
            baseline_at_ref(repo_root=repo_root, git_ref=args.baseline_ref)
            if args.baseline_ref is not None
            else None
        )
        selected = list(entries) if args.vendor_id is None else [args.vendor_id]
        if args.all and args.keep_sha and baseline is not None:
            with tempfile.TemporaryDirectory(prefix="vendor-repin-") as tmp:
                path = Path(tmp) / MANIFEST
                path.write_text(baseline.manifest_text, encoding="utf-8")
                previous = read_document(path)
            selected = [
                vendor_id
                for vendor_id in selected
                if find_vendor(previous, vendor_id) != entries[vendor_id]
            ]
        supplied = vendor_roots(args.vendor_root)
    except _CLI_FAILURES as error:
        print(safe_diagnostic(str(error)), file=sys.stderr)
        return 1
    reports: list[RepinReport] = []
    for vendor_id in selected:
        try:
            report = repin_vendor(
                root=repo_root,
                vendor_id=vendor_id,
                revision=args.revision,
                keep_sha=args.keep_sha,
                baseline=baseline,
                supplied={
                    key: value for key, value in supplied.items() if key == vendor_id
                },
                resolve=_resolve,
                declined=_declined if args.skip_declined else None,
                rewrite_manifest=not args.no_manifest_rewrite,
            )
        except _CLI_FAILURES as error:
            report = _failure_report(entry=entries[vendor_id], error=error)
        for line in report.action_required:
            print(f"repin: {vendor_id}: {line}", file=sys.stderr)
        reports.append(report)
    bodies = [render_markdown(report) for report in reports]
    if args.json:
        payload = [to_json(report) for report in reports]
        print(
            json.dumps(
                payload[0] if args.vendor_id is not None else payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
        )
    else:
        print("\n".join(bodies), end="")
    if args.summary_path is not None:
        args.summary_path.write_text(
            "\n".join(bodies) or "No vendor pin or slice changes.\n",
            encoding="utf-8",
        )
    return 1 if any(report.failed for report in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
