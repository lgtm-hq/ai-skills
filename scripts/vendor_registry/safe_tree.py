"""Symlink-rejecting tree walks and copies for vendor bake."""

from __future__ import annotations

import ctypes
import functools
import os
import shutil
import sys
from collections.abc import Iterator, Sequence
from contextlib import suppress
from ctypes.util import find_library
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

_AT_FDCWD = -100
_RENAME_EXCHANGE = 2
_RENAME_SWAP = 0x00000002
_REMOTE_LINK_SCHEMES = frozenset({"http", "https", "mailto", "data"})


class _BakeMarkdownIt(MarkdownIt):
    """CommonMark parser that keeps destinations bake must reject.

    The default validator blanks ``file:``, ``javascript:``, and
    ``vbscript:`` hrefs, which would skip ``_local_markdown_path``.
    """

    def validateLink(self, url: str) -> bool:
        """Keep hrefs so bake scheme checks can reject them.

        Args:
            url: Candidate href or src.

        Returns:
            Always ``True``.
        """
        del url
        return True


_COMMONMARK = _BakeMarkdownIt("commonmark")


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

    Destinations are taken from a CommonMark parse of each markdown file.
    Remote URLs and in-page anchors are ignored. Query and fragment
    components are not filename characters. Relative path components must
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
        for raw_target in _iter_markdown_destinations(text=text):
            _assert_relative_markdown_target(
                raw_target=raw_target,
                file_path=file_path,
                root=root,
            )


def _iter_markdown_destinations(*, text: str) -> Iterator[str]:
    """Yield CommonMark link and image destinations from ``text``.

    Destinations come from a CommonMark parser so code spans, nested
    brackets, wrapped link text, blockquoted definitions, and unused
    reference definitions are included. Percent-encoded hrefs are left
    encoded here and decoded before path checks.

    Args:
        text: Markdown source.

    Yields:
        Destinations as reported by the parser.
    """
    env: dict[str, object] = {}
    tokens = _COMMONMARK.parse(src=text, env=env)
    yield from _iter_token_destinations(tokens=tokens)
    yield from _iter_reference_destinations(env=env)


def _iter_token_destinations(*, tokens: Sequence[Token]) -> Iterator[str]:
    """Yield href/src attributes from link and image tokens.

    Args:
        tokens: Parsed CommonMark tokens, including children.

    Yields:
        Destination strings from ``link_open`` and ``image`` tokens.
    """
    for token in tokens:
        if token.type == "link_open":
            href = token.attrGet("href")
            if isinstance(href, str) and href:
                yield href
        elif token.type == "image":
            src = token.attrGet("src")
            if isinstance(src, str) and src:
                yield src
        if token.children:
            yield from _iter_token_destinations(tokens=token.children)


def _iter_reference_destinations(*, env: dict[str, object]) -> Iterator[str]:
    """Yield destinations from unused and used link reference definitions.

    Args:
        env: markdown-it parse environment that may contain ``references``.

    Yields:
        Definition hrefs, including blockquoted unused definitions.
    """
    references = env.get("references")
    if not isinstance(references, dict):
        return
    for record in references.values():
        if not isinstance(record, dict):
            continue
        href = record.get("href")
        if isinstance(href, str) and href:
            yield href


def _local_markdown_path(*, raw_target: str) -> str | None:
    """Return the local path component of a markdown destination.

    Query and fragment are dropped. The remaining path is then
    percent-decoded. Remote ``http``/``https``/``mailto``/``data`` URLs
    and empty paths are ignored.

    Args:
        raw_target: Destination from the CommonMark parser.

    Returns:
        Decoded path to resolve, or ``None`` to skip.

    Raises:
        ValueError: If the destination uses an unsafe scheme or contains
            a backslash.
    """
    parts = urlsplit(raw_target)
    scheme = parts.scheme.lower()
    if scheme in _REMOTE_LINK_SCHEMES:
        return None
    if not scheme and parts.netloc:
        return None
    if scheme:
        msg = f"path escape rejected: {raw_target}"
        raise ValueError(msg)
    path = unquote(parts.path)
    if not path:
        return None
    if "\\" in path or "\0" in path:
        msg = f"path escape rejected: {raw_target}"
        raise ValueError(msg)
    return path


def _assert_relative_markdown_target(
    *,
    raw_target: str,
    file_path: Path,
    root: Path,
) -> None:
    """Fail closed when a relative markdown target is missing or escapes.

    Args:
        raw_target: Link destination from the CommonMark parser.
        file_path: Markdown file that contains the link.
        root: Plugin tree the target must stay inside.

    Raises:
        ValueError: If the target escapes ``root`` or is not an existing
            file.
    """
    target = _local_markdown_path(raw_target=raw_target)
    if target is None:
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


def _reject_leftover_backup(*, destination: Path) -> None:
    """Fail closed when a leftover bake backup path already exists.

    Args:
        destination: Final output path whose sibling ``.{name}.bak`` must
            not already exist.

    Raises:
        ValueError: If a leftover backup directory, file, or dangling
            symlink is present.
    """
    leftover = destination.with_name(f".{destination.name}.bak")
    if leftover.exists(follow_symlinks=False):
        msg = f"leftover bake backup: {leftover}"
        raise ValueError(msg)


def install_directory(*, source: Path, destination: Path) -> None:
    """Publish a completed ``source`` tree onto ``destination``.

    When ``destination`` already exists, the staged tree is exchanged onto
    the destination path in one kernel rename so that path is never absent
    or mixed, then the new contents are mirrored onto the original
    destination inode and exchanged back. A process whose cwd is
    ``destination`` keeps a valid working directory, including when the
    inode mirror fails: the original inode is swapped back onto
    ``destination`` before the error propagates. When ``destination``
    does not exist, ``source`` is renamed onto it. A leftover
    ``.{name}.bak`` next to ``destination`` always fails closed.

    Args:
        source: Completed tree on the same filesystem as ``destination``.
        destination: Final output path.

    Raises:
        ValueError: If ``source`` or ``destination`` is a symlink, or a
            leftover backup path already exists (including a dangling
            symlink).
        OSError: If the exchange or mirror fails.
    """
    if source.is_symlink():
        msg = f"symlink rejected: {source}"
        raise ValueError(msg)
    if destination.is_symlink():
        msg = f"symlink rejected: {destination}"
        raise ValueError(msg)
    _reject_leftover_backup(destination=destination)
    if destination.exists(follow_symlinks=False):
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
        ValueError: If a leftover backup path already exists.
        OSError: If an exchange or mirror copy fails.
    """
    _reject_leftover_backup(destination=destination)
    _exchange_paths(first=source, second=destination)
    try:
        _mirror_tree(source=destination, destination=source)
    except BaseException:
        with suppress(OSError):
            _exchange_paths(first=source, second=destination)
        raise
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
        if dest_child.exists(follow_symlinks=False):
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
