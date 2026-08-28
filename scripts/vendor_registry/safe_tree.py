"""Symlink-rejecting tree walks and copies for vendor bake."""

from __future__ import annotations

import ctypes
import functools
import os
import shutil
import sys
from collections.abc import Iterator
from ctypes.util import find_library
from pathlib import Path

_AT_FDCWD = -100
_RENAME_EXCHANGE = 2
_RENAME_SWAP = 0x00000002


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

    When ``destination`` already exists, the two directories are exchanged
    with a single kernel rename so the destination path is never absent.
    The previous tree is left at ``source`` for the caller to delete.
    When ``destination`` does not exist, ``source`` is renamed onto it.

    Args:
        source: Completed tree on the same filesystem as ``destination``.
        destination: Final output path.

    Raises:
        ValueError: If ``source`` or ``destination`` is a symlink.
        OSError: If the exchange or rename fails.
    """
    if source.is_symlink():
        msg = f"symlink rejected: {source}"
        raise ValueError(msg)
    if destination.is_symlink():
        msg = f"symlink rejected: {destination}"
        raise ValueError(msg)
    if destination.exists():
        _exchange_paths(first=source, second=destination)
        return
    source.rename(target=destination)


@functools.cache
def _libc() -> ctypes.CDLL:
    """Return the process libc for atomic directory exchange.

    Returns:
        Loaded libc.

    Raises:
        OSError: If libc cannot be loaded.
    """
    libname = find_library(name="c")
    if libname is None:
        msg = "libc not found"
        raise OSError(msg)
    return ctypes.CDLL(name=libname, use_errno=True)


def _exchange_paths(*, first: Path, second: Path) -> None:
    """Atomically swap two existing paths on the same filesystem.

    Args:
        first: First path (the staged tree).
        second: Second path (the live destination).

    Raises:
        OSError: If the platform cannot exchange directories or the
            syscall fails.
    """
    if sys.platform == "linux":
        _linux_rename_exchange(first=first, second=second)
        return
    if sys.platform == "darwin":
        _darwin_rename_swap(first=first, second=second)
        return
    msg = f"atomic directory exchange is not supported on {sys.platform}"
    raise OSError(msg)


def _linux_rename_exchange(*, first: Path, second: Path) -> None:
    """Swap two paths with ``renameat2(RENAME_EXCHANGE)``.

    Args:
        first: First path.
        second: Second path.

    Raises:
        OSError: If the syscall fails.
    """
    libc = _libc()
    libc.renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    libc.renameat2.restype = ctypes.c_int
    result = libc.renameat2(
        _AT_FDCWD,
        os.fsencode(first),
        _AT_FDCWD,
        os.fsencode(second),
        _RENAME_EXCHANGE,
    )
    if result != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(first), None, str(second))


def _darwin_rename_swap(*, first: Path, second: Path) -> None:
    """Swap two paths with ``renamex_np(RENAME_SWAP)``.

    Args:
        first: First path.
        second: Second path.

    Raises:
        OSError: If the syscall fails.
    """
    libc = _libc()
    libc.renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    libc.renamex_np.restype = ctypes.c_int
    result = libc.renamex_np(
        os.fsencode(first),
        os.fsencode(second),
        _RENAME_SWAP,
    )
    if result != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(first), None, str(second))
