"""Safe payload paths and deterministic byte/mode hashing."""

import hashlib
import json
import stat
from pathlib import Path, PurePosixPath

from ai_skills_engine.inventory.payload_file import PayloadFile
from ai_skills_engine.registry.safe_tree import contained_path, walk_files


def source_path(*, root: Path, relative: str) -> Path:
    """Validate a repository-relative operand including every ancestor.

    Args:
        root: Explicit repository input.
        relative: Declared POSIX source path.

    Returns:
        Safe existing source path.

    Raises:
        ValueError: On traversal, symlinks, missing or special nodes.
    """
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative or not relative:
        raise ValueError(f"Unsafe source path: {relative}")
    current = root
    for part in (".", *pure.parts):
        current = current / part
        contained_path(path=current, root=root)
    if not current.is_file() and not current.is_dir():
        raise ValueError(f"Missing or unsupported payload: {relative}")
    return current


def payload_files(source: Path) -> tuple[PayloadFile, ...]:
    """Hash a safe regular file or directory without interpreting its code.

    Modes record Git-like executable identity: owner execute means 0755,
    otherwise 0644. Read/write, group/other execute and special bits are not
    identity. The owner bit also survives tarfile's data filter, unlike a
    group/other-only execute bit. Collection never chmods source files.

    Args:
        source: Previously boundary-checked path.

    Returns:
        Sorted file observations with canonical 0644 or 0755 modes.
    """
    base = source if source.is_dir() else source.parent
    files = walk_files(root=source) if source.is_dir() else iter((source,))
    return tuple(
        sorted(
            (
                PayloadFile(
                    path=PurePosixPath(path.relative_to(base).as_posix()),
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    mode=0o755 if path.stat().st_mode & stat.S_IXUSR else 0o644,
                )
                for path in files
            ),
            key=lambda item: item.path.as_posix(),
        ),
    )


def tree_digest(payload: tuple[PayloadFile, ...]) -> str:
    """Hash unambiguous sorted path/hash/mode triples.

    Args:
        payload: Sorted payload observations.

    Returns:
        SHA-256 of compact ASCII JSON triples.
    """
    triples = [(str(item.path), item.sha256, item.mode) for item in payload]
    return hashlib.sha256(
        json.dumps(triples, separators=(",", ":")).encode()
    ).hexdigest()
