"""Crash- and concurrency-safe file publication: temp file, fsync, then rename."""

import os
from contextlib import suppress
from pathlib import Path
from tempfile import mkstemp


def atomic_write(*, path: Path, data: bytes, mode: int = 0o644) -> None:
    """Publish complete bytes so concurrent readers never observe partial files.

    Writers use a private sibling temporary file, flush and fsync it, then
    rename it over the destination. Concurrent writers of identical content
    (for example parallel CI jobs filling one content-addressed cache) race
    harmlessly: each rename publishes a complete file.

    Args:
        path: Final destination.
        data: Complete file contents.
        mode: Permission bits for the published file.

    Raises:
        OSError: If the destination directory cannot be written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def _fsync_directory(directory: Path) -> None:
    """Persist the rename itself where the platform supports directory fsync.

    Args:
        directory: Parent directory containing the renamed entry.
    """
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        with suppress(OSError):
            os.fsync(descriptor)
    finally:
        os.close(descriptor)
