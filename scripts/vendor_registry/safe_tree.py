"""Symlink-rejecting tree walks and copies for vendor bake."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path


def iter_directory_entries(*, directory: Path) -> Iterator[Path]:
    """Yield direct children of ``directory`` in name order.

    Args:
        directory: Directory to list.

    Yields:
        Child paths.

    Raises:
        ValueError: If ``directory`` is a symlink.
    """
    if directory.is_symlink():
        msg = f"symlink rejected: {directory}"
        raise ValueError(msg)
    yield from sorted(directory.iterdir(), key=lambda path: path.name)


def walk_files(*, root: Path) -> Iterator[Path]:
    """Walk files under ``root``, rejecting symlinks and special nodes.

    Args:
        root: Tree root. Must not itself be a symlink.

    Yields:
        Regular files under ``root``.

    Raises:
        ValueError: If a symlink or unsupported node is encountered.
    """
    if root.is_symlink():
        msg = f"symlink rejected: {root}"
        raise ValueError(msg)
    stack = [root]
    while stack:
        current = stack.pop()
        for child in iter_directory_entries(directory=current):
            if child.is_symlink():
                msg = f"symlink rejected: {child}"
                raise ValueError(msg)
            if child.is_dir():
                stack.append(child)
                continue
            if not child.is_file():
                msg = f"unsupported file type rejected: {child}"
                raise ValueError(msg)
            yield child


def contained_path(*, path: Path, root: Path) -> Path:
    """Return ``path`` resolved and confirm it stays inside ``root``.

    Args:
        path: Path that must resolve inside ``root``.
        root: Tree that must contain ``path``.

    Returns:
        The resolved path.

    Raises:
        ValueError: If ``path`` is a symlink or escapes ``root``.
    """
    if path.is_symlink():
        msg = f"symlink rejected: {path}"
        raise ValueError(msg)
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        msg = f"path escape rejected: {path}"
        raise ValueError(msg) from exc
    return resolved_path


def copy_tree(*, source: Path, destination: Path, source_root: Path) -> None:
    """Copy ``source`` into ``destination`` without following symlinks.

    Args:
        source: Directory to copy.
        destination: New directory that will hold the copy.
        source_root: Vendor tree that ``source`` must stay inside.

    Raises:
        ValueError: If ``source`` escapes ``source_root``, is a symlink, or
            contains a symlink / unsupported node.
        FileExistsError: If ``destination`` already exists.
    """
    contained_path(path=source, root=source_root)
    if destination.exists():
        msg = f"destination already exists: {destination}"
        raise FileExistsError(msg)
    destination.mkdir(parents=True)
    for file_path in walk_files(root=source):
        relative = file_path.relative_to(source)
        target = destination / relative
        contained_path(path=target.parent, root=destination.parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src=file_path, dst=target)


def validate_tree(*, root: Path) -> None:
    """Reject symlinks and path escapes anywhere under ``root``.

    Args:
        root: Tree to validate.

    Raises:
        ValueError: If a symlink, escape, or unsupported node is found.
    """
    contained_path(path=root, root=root)
    for file_path in walk_files(root=root):
        contained_path(path=file_path, root=root)


def find_skill_markdown(*, root: Path) -> tuple[str, ...]:
    """Return POSIX paths of every ``SKILL.md`` under ``root``.

    Args:
        root: Vendor tree to scan.

    Returns:
        Sorted paths relative to ``root``.
    """
    found = [
        file_path.relative_to(root).as_posix()
        for file_path in walk_files(root=root)
        if file_path.name == "SKILL.md"
    ]
    return tuple(sorted(found))


def install_directory(*, source: Path, destination: Path) -> None:
    """Publish a completed ``source`` tree onto ``destination``.

    When ``destination`` already exists, children are replaced in place so
    the destination path and directory inode stay put. A process whose
    cwd is ``destination`` remains valid. The destination directory is
    never removed. On failure, previous children are restored. When
    ``destination`` does not exist, ``source`` is renamed onto it.

    Args:
        source: Completed tree on the same filesystem as ``destination``.
        destination: Final output path.

    Raises:
        ValueError: If ``source`` or ``destination`` is a symlink, or a
            leftover backup directory already exists.
        OSError: If the child replace or rename fails.
    """
    if source.is_symlink():
        msg = f"symlink rejected: {source}"
        raise ValueError(msg)
    if destination.is_symlink():
        msg = f"symlink rejected: {destination}"
        raise ValueError(msg)
    if destination.exists():
        _replace_directory_children(source=source, destination=destination)
        return
    source.rename(target=destination)


def _replace_directory_children(*, source: Path, destination: Path) -> None:
    """Move ``source`` children into ``destination`` without renaming dest.

    Args:
        source: Staged tree whose children will be published.
        destination: Live directory whose inode must be preserved.

    Raises:
        ValueError: If a leftover backup directory already exists.
        OSError: If a child rename fails after previous children were
            moved aside.
    """
    backup = destination.with_name(f".{destination.name}.bak")
    if backup.exists():
        msg = f"leftover bake backup: {backup}"
        raise ValueError(msg)
    backup.mkdir()
    try:
        for child in list(destination.iterdir()):
            child.rename(target=backup / child.name)
        for child in list(source.iterdir()):
            child.rename(target=destination / child.name)
    except OSError:
        _restore_directory_children(destination=destination, backup=backup)
        raise
    shutil.rmtree(backup)


def _restore_directory_children(*, destination: Path, backup: Path) -> None:
    """Put ``backup`` children back into ``destination`` after a failed swap.

    Args:
        destination: Live directory that may hold a partial new tree.
        backup: Directory holding the previous children.
    """
    for child in list(destination.iterdir()):
        _remove_path(path=child)
    for child in list(backup.iterdir()):
        child.rename(target=destination / child.name)
    if backup.exists():
        shutil.rmtree(backup)


def _remove_path(*, path: Path) -> None:
    """Remove a file or directory.

    Args:
        path: Path to unlink or recursively delete.
    """
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
        return
    path.unlink()
