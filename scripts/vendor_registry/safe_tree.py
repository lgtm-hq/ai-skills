"""Symlink-rejecting tree walks and copies for vendor bake."""

from __future__ import annotations

import ctypes
import functools
import os
import re
import shutil
import sys
from collections.abc import Iterator
from ctypes.util import find_library
from pathlib import Path

_AT_FDCWD = -100
_RENAME_EXCHANGE = 2
_RENAME_SWAP = 0x00000002
_MARKDOWN_LINK_TARGET = re.compile(
    r"\[[^\]\n]*\]\(\s*<?([^>\s)]+)[^)]*>?\)",
)
_MARKDOWN_REF_DEF = re.compile(
    r"^[ \t]*\[([^\]]+)\]:[ \t]*<?([^\s>]+)",
    re.MULTILINE,
)
_REMOTE_LINK_PREFIXES = ("http://", "https://", "mailto:", "data:")


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


def walk_directories(*, root: Path) -> Iterator[Path]:
    """Walk directories under ``root``, rejecting symlinks.

    Args:
        root: Tree root. Must not itself be a symlink.

    Yields:
        Directories under ``root``, excluding ``root`` itself.

    Raises:
        ValueError: If a symlink is encountered.
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
                yield child
                stack.append(child)


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
    for dir_path in walk_directories(root=source):
        target = destination / dir_path.relative_to(source)
        contained_path(path=target, root=destination)
        target.mkdir(parents=True, exist_ok=True)
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


def validate_internal_references(*, root: Path) -> None:
    """Reject markdown links that escape ``root`` or point at missing files.

    Remote URLs and in-page anchors are ignored. Relative targets must
    resolve to an existing file inside ``root``.

    Args:
        root: Plugin tree to validate.

    Raises:
        ValueError: If a relative markdown link escapes ``root`` or the
            target file does not exist.
    """
    for file_path in walk_files(root=root):
        if file_path.suffix.lower() not in {".md", ".markdown"}:
            continue
        text = file_path.read_text(encoding="utf-8")
        for match in _MARKDOWN_LINK_TARGET.finditer(text):
            _assert_relative_markdown_target(
                raw_target=match.group(1),
                file_path=file_path,
                root=root,
            )
        for match in _MARKDOWN_REF_DEF.finditer(text):
            _assert_relative_markdown_target(
                raw_target=match.group(2),
                file_path=file_path,
                root=root,
            )


def _assert_relative_markdown_target(
    *,
    raw_target: str,
    file_path: Path,
    root: Path,
) -> None:
    """Fail closed when a relative markdown target is missing or escapes.

    Args:
        raw_target: Link destination from inline syntax or a reference
            definition.
        file_path: Markdown file that contains the link.
        root: Plugin tree the target must stay inside.

    Raises:
        ValueError: If the target escapes ``root`` or is not an existing
            file.
    """
    target = raw_target.split("#", maxsplit=1)[0]
    if not target or target.lower().startswith(_REMOTE_LINK_PREFIXES):
        return
    resolved = (file_path.parent / target).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        msg = f"path escape rejected: {raw_target}"
        raise ValueError(msg) from exc
    if not resolved.is_file():
        msg = f"internal reference missing: {raw_target}"
        raise ValueError(msg)


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

    When ``destination`` already exists, the staged tree is exchanged onto
    the destination path in one kernel rename so that path is never absent
    or mixed, then the new contents are mirrored onto the original
    destination inode and exchanged back. A process whose cwd is
    ``destination`` keeps a valid working directory. When ``destination``
    does not exist, ``source`` is renamed onto it.

    Args:
        source: Completed tree on the same filesystem as ``destination``.
        destination: Final output path.

    Raises:
        ValueError: If ``source`` or ``destination`` is a symlink, or a
            leftover backup directory already exists.
        OSError: If the exchange or mirror fails.
    """
    if source.is_symlink():
        msg = f"symlink rejected: {source}"
        raise ValueError(msg)
    if destination.is_symlink():
        msg = f"symlink rejected: {destination}"
        raise ValueError(msg)
    if destination.exists():
        _publish_into_existing(source=source, destination=destination)
        return
    source.rename(target=destination)


def _publish_into_existing(*, source: Path, destination: Path) -> None:
    """Atomically publish ``source`` while restoring the dest inode.

    The destination path is swapped onto the staged tree first so readers
    never see a mixed generation. The new tree is then copied onto the
    original destination inode and swapped back.

    Args:
        source: Staged complete tree.
        destination: Live directory whose inode should be preserved.

    Raises:
        ValueError: If a leftover backup directory already exists.
        OSError: If an exchange or mirror copy fails.
    """
    leftover = destination.with_name(f".{destination.name}.bak")
    if leftover.exists():
        msg = f"leftover bake backup: {leftover}"
        raise ValueError(msg)
    _exchange_paths(first=source, second=destination)
    _mirror_tree(source=destination, destination=source)
    _exchange_paths(first=source, second=destination)


def _mirror_tree(*, source: Path, destination: Path) -> None:
    """Make ``destination`` children match ``source`` without renaming dest.

    Args:
        source: Tree whose children are the desired contents.
        destination: Directory whose inode must be preserved.

    Raises:
        ValueError: If a child is a symlink or unsupported node.
        OSError: If a copy or removal fails.
    """
    incoming = {child.name for child in source.iterdir()}
    for child in list(source.iterdir()):
        dest_child = destination / child.name
        if dest_child.exists():
            _remove_path(path=dest_child)
        if child.is_dir():
            copy_tree(source=child, destination=dest_child, source_root=source)
            continue
        if not child.is_file():
            msg = f"unsupported file type rejected: {child}"
            raise ValueError(msg)
        shutil.copy2(src=child, dst=dest_child)
    for dest_child in list(destination.iterdir()):
        if dest_child.name not in incoming:
            _remove_path(path=dest_child)


def _remove_path(*, path: Path) -> None:
    """Remove a file or directory.

    Args:
        path: Path to unlink or recursively delete.
    """
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
        return
    path.unlink()


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
