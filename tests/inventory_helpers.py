"""Shared inventory fixture preparation, with no network or vendor execution."""

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "inventory"


def snapshot(*roots: Path) -> dict[str, tuple[bytes, int]]:
    """Capture every consumer/vendor file byte and permission bit.

    Args:
        roots: Independent fixture inputs.

    Returns:
        File contents and modes keyed by absolute path.
    """
    return {
        str(path): (path.read_bytes(), path.stat().st_mode & 0o7777)
        for root in roots
        for path in root.rglob("*")
        if path.is_file()
    }


def copy_inventory_fixture(destination: Path) -> tuple[Path, Path]:
    """Copy the full fixture publisher and manifestless vendor inputs.

    Args:
        destination: Isolated scratch directory.

    Returns:
        Publisher root and vendor root.
    """
    root, vendor = destination / "publisher", destination / "vendor"
    shutil.copytree(src=FIXTURES / "publisher", dst=root)
    shutil.copytree(src=FIXTURES / "vendor", dst=vendor)
    return root, vendor


@pytest.fixture
def inventory_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    """Prepare inventory fixtures with a network guard.

    Args:
        tmp_path: Isolated publisher/vendor roots.
        monkeypatch: Network guard.

    Returns:
        Publisher and vendor paths.
    """

    def forbidden(*args: object, **kwargs: object) -> None:
        """Reject accidental vendor fetches or endpoint connections."""
        pytest.fail("Unit inventory collection must be offline")

    monkeypatch.setattr("socket.socket.connect", forbidden)
    return copy_inventory_fixture(tmp_path)
