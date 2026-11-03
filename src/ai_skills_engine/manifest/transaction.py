"""Exact file snapshots shared by manifest publication and vendor rollback."""

import stat
from collections.abc import Iterable
from pathlib import Path

FileSnapshots = dict[Path, tuple[bytes, int] | None]


def snapshot_files(paths: Iterable[Path]) -> FileSnapshots:
    """Capture bytes, permission bits and absence before any destination write.

    Args:
        paths: Publication destinations to capture.

    Returns:
        Independent original state for each path.
    """
    return {
        path: (
            (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            if path.exists()
            else None
        )
        for path in paths
    }


def restore_files(*, originals: FileSnapshots, error: BaseException) -> None:
    """Restore each publication independently, retaining cleanup evidence on failure.

    Args:
        originals: Original bytes and modes, or absence, for every destination.
        error: Original failure to annotate without replacing it.
    """
    for destination, previous in originals.items():
        try:
            if previous is None:
                destination.unlink(missing_ok=True)
            else:
                content, mode = previous
                if not destination.exists() or destination.read_bytes() != content:
                    destination.write_bytes(content)
                if stat.S_IMODE(destination.stat().st_mode) != mode:
                    destination.chmod(mode)
        except OSError as cleanup_error:
            action = (
                "remove the newly created file"
                if previous is None
                else f"restore its original bytes and mode {previous[1]:#o}"
            )
            error.add_note(
                f"Transaction cleanup failed for {destination}: {cleanup_error!r}; "
                f"manually {action} before retrying."
            )
