"""Symlink-rejecting tree walks and copies for vendor bake."""

from __future__ import annotations

import ctypes
import functools
import os
import shutil
import stat
import sys
from collections.abc import Iterator, Sequence
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
    if destination.exists(follow_symlinks=False) or destination.is_symlink():
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
        _copy_file_nofollow(source=file_path, destination=target)


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
    """Fail closed when a leftover bake sidecar already exists.

    Args:
        destination: Final output path whose sibling ``.{name}.bak`` and
            ``.{name}.hold`` must not already exist.

    Raises:
        ValueError: If a leftover backup or hold directory, file, or
            dangling symlink is present.
    """
    leftovers = (
        (destination.with_name(f".{destination.name}.bak"), "backup"),
        (destination.with_name(f".{destination.name}.hold"), "hold"),
    )
    for leftover, label in leftovers:
        if leftover.exists(follow_symlinks=False):
            msg = f"leftover bake {label}: {leftover}"
            raise ValueError(msg)


def _hold_path(*, destination: Path) -> Path:
    """Return the sibling directory that parks the original dest inode.

    Args:
        destination: Final output path.

    Returns:
        ``.{name}.hold`` next to ``destination``.
    """
    return destination.with_name(f".{destination.name}.hold")


def install_directory(*, source: Path, destination: Path) -> None:
    """Publish a completed ``source`` tree onto ``destination``.

    When ``destination`` already exists, the staged tree is exchanged onto
    the destination path in one kernel rename so that path is never absent
    or mixed. The original destination inode is moved to a sibling hold
    directory (outside any caller temporary tree), snapshotted, then
    filled with the new contents and exchanged back. On mirror failure the
    snapshot is copied back onto that inode before it returns to
    ``destination``, so readers and a resident cwd see the complete old
    tree. When ``destination`` does not exist, ``source`` is renamed onto
    it. Leftover ``.{name}.bak`` or ``.{name}.hold`` sidecars fail closed.

    Args:
        source: Completed tree on the same filesystem as ``destination``.
        destination: Final output path.

    Raises:
        ValueError: If ``source`` or ``destination`` is a symlink, or a
            leftover backup or hold path already exists (including a
            dangling symlink).
        OSError: If the exchange or mirror fails.
        ExceptionGroup: If rollback cannot restore the original inode to
            ``destination``; both the publish error and the restore error
            are raised, and the hold directory is left in place so the
            original inode is not unlinked.
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
    never see a mixed generation. The original inode is parked in a
    sibling hold directory, snapshotted, filled with the new tree, and
    swapped back.

    Args:
        source: Staged complete tree.
        destination: Live directory whose inode should be preserved.

    Raises:
        ValueError: If a leftover backup or hold path already exists.
        OSError: If an exchange or mirror copy fails.
        ExceptionGroup: If rollback cannot put the original inode back.
    """
    _reject_leftover_backup(destination=destination)
    original_inode = destination.stat().st_ino
    hold = _hold_path(destination=destination)
    inode_home = hold / "inode"
    snapshot = hold / "snapshot"
    hold.mkdir()
    exchanged = False
    parked = False
    try:
        _exchange_paths(first=source, second=destination)
        exchanged = True
        source.rename(target=inode_home)
        parked = True
        snapshot.mkdir()
        _replace_tree_contents(source=inode_home, destination=snapshot)
        try:
            _mirror_tree(source=destination, destination=inode_home)
            _exchange_paths(first=inode_home, second=destination)
        except BaseException as exc:  # noqa: BLE001 - restore dest inode on interrupt
            _rollback_original_inode(
                snapshot=snapshot,
                inode_home=inode_home,
                destination=destination,
                original=exc,
            )
    except BaseException as exc:
        if exchanged and not parked:
            try:
                _exchange_paths(first=source, second=destination)
            except BaseException as restore_exc:  # noqa: BLE001 - pair with publish error
                _raise_publish_failures(original=exc, restore=restore_exc)
        raise
    finally:
        if _inode_is(
            path=destination,
            ino=original_inode,
        ) and hold.exists(follow_symlinks=False):
            _remove_path(path=hold)


def _rollback_original_inode(
    *,
    snapshot: Path,
    inode_home: Path,
    destination: Path,
    original: BaseException,
) -> None:
    """Put complete old contents on the original inode and swap it back.

    Args:
        snapshot: Complete copy of the pre-publish destination tree.
        inode_home: Current path of the original destination inode.
        destination: Live destination path.
        original: Error that interrupted publish.

    Raises:
        ExceptionGroup: If restoring contents or exchanging back fails.
        BaseException: Re-raises ``original`` after a successful restore.
    """
    try:
        if snapshot.exists(follow_symlinks=False):
            _replace_tree_contents(source=snapshot, destination=inode_home)
        _exchange_paths(first=inode_home, second=destination)
    except BaseException as restore_exc:  # noqa: BLE001 - pair with publish error
        _raise_publish_failures(original=original, restore=restore_exc)
    raise original


def _raise_publish_failures(
    *,
    original: BaseException,
    restore: BaseException,
) -> None:
    """Raise both publish failures when they can join an ``ExceptionGroup``.

    Args:
        original: Error that interrupted publish.
        restore: Error from attempting to restore the original inode.

    Raises:
        ExceptionGroup: When both errors are ``Exception`` instances.
        BaseException: ``restore`` when either error cannot join an
            ``ExceptionGroup``.
    """
    if isinstance(original, Exception) and isinstance(restore, Exception):
        raise ExceptionGroup(
            "bake destination publish failed",
            [original, restore],
        ) from original
    raise restore from original


def _inode_is(*, path: Path, ino: int) -> bool:
    """Return whether ``path`` is a non-symlink directory with inode ``ino``.

    Args:
        path: Path to inspect.
        ino: Expected inode number.

    Returns:
        ``True`` when ``path`` exists, is not a symlink, and matches
        ``ino``.
    """
    try:
        status = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(status.st_mode):
        return False
    return status.st_ino == ino


def _mirror_tree(*, source: Path, destination: Path) -> None:
    """Make ``destination`` children match ``source`` without renaming dest.

    Args:
        source: Tree whose children are the desired contents.
        destination: Directory whose inode must be preserved.

    Raises:
        ValueError: If a child is a symlink or unsupported node.
        OSError: If a copy or removal fails.
    """
    _replace_tree_contents(source=source, destination=destination)


def _replace_tree_contents(*, source: Path, destination: Path) -> None:
    """Replace ``destination`` children with ``source`` without following links.

    Copies use a directory file descriptor and ``O_EXCL|O_NOFOLLOW`` so a
    symlink planted after the existence check cannot redirect the write.
    Destination-side dangling symlinks are snapshotted as symlinks.

    Args:
        source: Tree whose children are the desired contents.
        destination: Directory whose inode must be preserved.

    Raises:
        ValueError: If a child is an unsupported node.
        OSError: If a copy or removal fails.
        FileExistsError: If a dest name is replaced by a symlink during
            the exclusive create.
    """
    incoming = {child.name for child in source.iterdir()}
    for child in list(source.iterdir()):
        dest_child = destination / child.name
        if child.is_symlink():
            if dest_child.exists(follow_symlinks=False):
                _remove_path(path=dest_child)
            dest_child.symlink_to(os.readlink(child))
            continue
        if child.is_dir():
            if dest_child.exists(follow_symlinks=False):
                _remove_path(path=dest_child)
            dest_child.mkdir()
            _replace_tree_contents(source=child, destination=dest_child)
            continue
        if not child.is_file():
            msg = f"unsupported file type rejected: {child}"
            raise ValueError(msg)
        _copy_file_nofollow(source=child, destination=dest_child)
    for dest_child in list(destination.iterdir()):
        if dest_child.name not in incoming:
            _remove_path(path=dest_child)


def _copy_file_nofollow(*, source: Path, destination: Path) -> None:
    """Copy a regular file without following a destination symlink.

    Args:
        source: Regular file to copy.
        destination: Intended new file path.

    Raises:
        ValueError: If ``source`` is not a regular file.
        OSError: If the copy fails or ``destination`` is a symlink.
    """
    src_flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        src_flags |= os.O_NOFOLLOW
    src_fd = os.open(source, src_flags)
    try:
        info = os.fstat(src_fd)
        if not stat.S_ISREG(info.st_mode):
            msg = f"unsupported file type rejected: {source}"
            raise ValueError(msg)
        dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            dir_flags |= os.O_NOFOLLOW
        parent_fd = os.open(destination.parent, dir_flags)
        try:
            _remove_path(path=destination)
            _create_exclusive_copy_at(
                source_fd=src_fd,
                dir_fd=parent_fd,
                name=destination.name,
                mode=stat.S_IMODE(info.st_mode),
            )
        finally:
            os.close(parent_fd)
    finally:
        os.close(src_fd)


def _create_exclusive_copy_at(
    *,
    source_fd: int,
    dir_fd: int,
    name: str,
    mode: int,
) -> None:
    """Create ``name`` in ``dir_fd`` without following a planted symlink.

    ``O_CREAT|O_EXCL|O_NOFOLLOW`` fails closed when ``name`` already exists
    as a symlink, so the copy cannot write through an external target.

    Args:
        source_fd: Open read fd for the source regular file.
        dir_fd: Open directory file descriptor for the destination parent.
        name: Child name to create.
        mode: POSIX permission bits for the new file.

    Raises:
        OSError: If exclusive create or the copy fails.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    dst_fd = os.open(name, flags, mode, dir_fd=dir_fd)
    try:
        os.lseek(source_fd, 0, os.SEEK_SET)
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            os.write(dst_fd, chunk)
        os.fchmod(dst_fd, mode)
    finally:
        os.close(dst_fd)


def _remove_path(*, path: Path) -> None:
    """Remove a file, symlink, or directory without following links.

    Args:
        path: Path to unlink or recursively delete.
    """
    try:
        status = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISDIR(status.st_mode) and not stat.S_ISLNK(status.st_mode):
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
