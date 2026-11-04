"""``ai-skills-engine lock``: resolve pinned inputs into ``ai-skills.lock``.

- ``lock``: resolve changed manifest entries, fetch missing sources, rebuild in
  scratch and write the lock. Existing pins never move; repinning is ``repin``.
- ``lock --check``: no writes; fail if the lock is stale or differs from a
  cache-only rebuild (``--inputs-only`` skips the rebuild and needs no sources).
- ``lock --fetch``: fill the source cache for the existing lock only.
"""

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_skills_engine.artifacts.drift import report_difference
from ai_skills_engine.commands.source_mode import SourceMode
from ai_skills_engine.commands.sources import (
    build_lock,
    check_current,
    materialize_sources,
)
from ai_skills_engine.inventory.cli import vendor_roots
from ai_skills_engine.lockfile import (
    LOCK_FILENAME,
    LOCK_HINT,
    dumps,
    loads,
    read_lock,
    require_canonical,
    write_lock,
)
from ai_skills_engine.paths import resolve_repo_root
from ai_skills_engine.registry.ingest_checks import safe_diagnostic
from ai_skills_engine.source_cache import SourceCache

FAILURES = (OSError, RuntimeError, ValueError, TypeError, KeyError)


def _parser() -> argparse.ArgumentParser:
    """Define the command line.

    Returns:
        Argument parser.
    """
    parser = argparse.ArgumentParser(prog="ai-skills-engine lock", description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument(
        "--lock", type=Path, help=f"Lock path (default: {LOCK_FILENAME})"
    )
    parser.add_argument(
        "--vendor-root",
        "--vendor-tree",
        action="append",
        default=[],
        metavar="ID=PATH",
        help="Seed the cache from a local pinned snapshot instead of fetching",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--check", action="store_true", help="No writes; fail if the lock is stale"
    )
    modes.add_argument(
        "--fetch",
        action="store_true",
        help="Populate the source cache for the existing lock only",
    )
    parser.add_argument(
        "--inputs-only",
        action="store_true",
        help="With --check: offline manifest/input/builder check without sources",
    )
    return parser


def _check(*, root: Path, path: Path, inputs_only: bool) -> int:
    """Verify the committed lock without writing anything.

    Args:
        root: Manifest root.
        path: Lock file.
        inputs_only: Skip the cache-only rebuild.

    Returns:
        Zero when current; one on drift.
    """
    lock = read_lock(path)
    check_current(root=root, lock=lock)
    require_canonical(path=path, lock=lock)
    if inputs_only:
        return 0
    with TemporaryDirectory(prefix="ai-skills-lock-check-") as temporary:
        scratch = Path(temporary)
        roots, vendors = materialize_sources(
            root=root,
            cache=SourceCache.default(),
            scratch=scratch / "sources",
            mode=SourceMode.FROZEN,
            locked={item.id: item for item in lock.vendors},
        )
        rebuilt = dumps(
            build_lock(
                root=root,
                roots=roots,
                vendors=vendors,
                destination=scratch / "artifacts",
            )
        )
    committed = path.read_bytes()
    if committed != rebuilt:
        report_difference(actual=committed, expected=rebuilt, label=path.name)
        print(
            f"lock: {path.name} differs from a rebuild of locked inputs; " + LOCK_HINT,
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Resolve, check or fetch the resolution lock.

    Args:
        argv: Command arguments.

    Returns:
        Zero on success; one on stale, corrupt or unavailable inputs.
    """
    parser = _parser()
    args = parser.parse_args(argv)
    if args.inputs_only and not args.check:
        parser.error("--inputs-only requires --check")
    root = resolve_repo_root(override=args.repo_root, parser=parser).resolve()
    path = args.lock or root / LOCK_FILENAME
    try:
        supplied = vendor_roots(args.vendor_root)
        if args.check:
            if supplied:
                parser.error("--check reads only the source cache")
            return _check(root=root, path=path, inputs_only=args.inputs_only)
        existing = (
            read_lock(path)
            if args.fetch or path.exists(follow_symlinks=False)
            else None
        )
        with TemporaryDirectory(prefix="ai-skills-lock-") as temporary:
            scratch = Path(temporary)
            roots, vendors = materialize_sources(
                root=root,
                cache=SourceCache.default(),
                scratch=scratch / "sources",
                mode=SourceMode.FETCH if args.fetch else SourceMode.RESOLVE,
                locked={item.id: item for item in existing.vendors} if existing else {},
                supplied=supplied,
            )
            if args.fetch:
                print(f"lock: source cache holds {len(vendors)} locked source(s)")
                return 0
            lock = build_lock(
                root=root,
                roots=roots,
                vendors=vendors,
                destination=scratch / "artifacts",
            )
        written = write_lock(path=path, lock=lock)
        loads(path.read_bytes())
        print(f"lock: {'wrote' if written else 'unchanged'} {path.name}")
        return 0
    except FAILURES as error:
        print("lock: " + safe_diagnostic(str(error)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
