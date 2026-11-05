"""``ai-skills-engine build``: offline artifacts from ``ai-skills.lock`` and the cache.

The build never resolves or fetches. It refuses a stale or non-canonical lock
(naming the ``lock`` fix) and any missing or corrupted cache entry (naming the
``lock --fetch`` fix). The rebuilt artifacts must reproduce every locked digest
before they replace the output directory.
"""

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_skills_engine.artifacts.drift import report_difference
from ai_skills_engine.commands.lock import FAILURES
from ai_skills_engine.commands.source_mode import SourceMode
from ai_skills_engine.commands.sources import (
    build_lock,
    check_current,
    materialize_sources,
)
from ai_skills_engine.lockfile import (
    LOCK_FILENAME,
    dumps,
    read_lock,
    require_canonical,
)
from ai_skills_engine.lockmodel.lock import Lock
from ai_skills_engine.paths import resolve_repo_root
from ai_skills_engine.registry.ingest_checks import safe_diagnostic
from ai_skills_engine.registry.safe_tree import install_directory
from ai_skills_engine.source_cache import SourceCache


def _mismatches(*, locked: Lock, rebuilt: Lock) -> list[str]:
    """Describe package digest differences between the lock and a rebuild.

    Args:
        locked: Committed lock.
        rebuilt: Lock describing the rebuilt artifacts.

    Returns:
        One line per added, removed or changed package digest.
    """
    before = {item.id: item for item in locked.packages}
    after = {item.id: item for item in rebuilt.packages}
    lines = []
    for package in sorted(before.keys() | after.keys()):
        old, new = before.get(package), after.get(package)
        if old is None or new is None:
            lines.append(
                f"package {package}: {'not locked' if old is None else 'not built'}"
            )
        elif old.artifact_digest != new.artifact_digest:
            lines.append(
                f"package {package}: artifactDigest locked {old.artifact_digest}, "
                f"built {new.artifact_digest}"
            )
        elif old.tree_digest != new.tree_digest:
            lines.append(
                f"package {package}: treeDigest locked {old.tree_digest}, "
                f"built {new.tree_digest}"
            )
    return lines


def build_from_lock(*, root: Path, lock_path: Path, destination: Path) -> int:
    """Rebuild every artifact offline and publish it only if it matches the lock.

    Args:
        root: Manifest root.
        lock_path: Committed lock.
        destination: Artifact directory to replace atomically.

    Returns:
        Zero on success; one when the rebuild differs from the lock.

    Raises:
        ValueError: If the output path traverses a symbolic link.
    """
    lock = read_lock(lock_path)
    require_canonical(path=lock_path, lock=lock)
    check_current(root=root, lock=lock)
    if any(path.is_symlink() for path in (destination, *destination.parents)):
        raise ValueError("Symlink rejected in artifact output path")
    with TemporaryDirectory(prefix="ai-skills-build-") as sources:
        roots, vendors = materialize_sources(
            root=root,
            cache=SourceCache.default(),
            scratch=Path(sources),
            mode=SourceMode.FROZEN,
            locked={item.id: item for item in lock.vendors},
        )
        # Create the output parent only once every locked source is available.
        destination.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(
            prefix=".ai-skills-build-", dir=destination.parent
        ) as staged:
            output = Path(staged) / "artifacts"
            rebuilt = build_lock(
                root=root, roots=roots, vendors=vendors, destination=output
            )
            committed, regenerated = lock_path.read_bytes(), dumps(rebuilt)
            if committed != regenerated:
                for line in _mismatches(locked=lock, rebuilt=rebuilt):
                    print("build: " + line, file=sys.stderr)
                report_difference(
                    actual=committed, expected=regenerated, label=lock_path.name
                )
                print(
                    f"build: rebuilt artifacts differ from {lock_path.name}; nothing "
                    "was published",
                    file=sys.stderr,
                )
                return 1
            install_directory(source=output, destination=destination)
    print(f"build: {len(rebuilt.packages)} package artifact(s) match {lock_path.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Build artifacts offline from the frozen lock and source cache.

    Args:
        argv: Command arguments.

    Returns:
        Zero on success; one for stale locks, cache misses or digest mismatches.
    """
    parser = argparse.ArgumentParser(prog="ai-skills-engine build", description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument(
        "--lock", type=Path, help=f"Lock path (default: {LOCK_FILENAME})"
    )
    parser.add_argument("--output", type=Path, help="Default: dist/artifacts/")
    args = parser.parse_args(argv)
    root = resolve_repo_root(override=args.repo_root, parser=parser).resolve()
    try:
        return build_from_lock(
            root=root,
            lock_path=args.lock or root / LOCK_FILENAME,
            destination=(args.output or root / "dist/artifacts").absolute(),
        )
    except FAILURES as error:
        print("build: " + safe_diagnostic(str(error)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
