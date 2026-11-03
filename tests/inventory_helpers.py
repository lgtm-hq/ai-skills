"""Shared inventory fixture preparation, with no network or vendor execution."""

import io
import shutil
import stat
import tarfile
from pathlib import Path

import pytest

from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document

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


def inventory_tarball(root: Path) -> bytes:
    """Archive actual fixture bytes and modes with GitHub's root prefix.

    Args:
        root: Safe fixture snapshot to acquire through the real fetcher.

    Returns:
        Gzip tar bytes for the network boundary stub.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.add(root, arcname="snapshot")
    return buffer.getvalue()


def inventory_snapshot(*roots: Path) -> dict[Path, tuple[bytes | None, int]]:
    """Observe fixture bytes and all file/directory modes without executing code.

    Args:
        roots: Input trees to observe before and after acquisition.

    Returns:
        Exact bytes and permission bits keyed by input path.
    """
    return {
        path: (
            path.read_bytes() if path.is_file() else None,
            stat.S_IMODE(path.stat().st_mode),
        )
        for root in roots
        for path in (root, *root.rglob("*"))
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


def configure_inventory_aliases(*, root: Path, vendor: Path, control: str) -> None:
    """Prepare skill aliases with a matching specialist or an unused rename key.

    Args:
        root: Fixture consumer repository.
        vendor: Fixture manifestless vendor.
        control: Same-stem, specialist-only, unused, or ordinary skill case.
    """
    document = read_document(root / "ai-skills.yaml")
    package = document["vendors"][0]["mapping"]["packages"][0]
    if control == "same-stem":
        skill = vendor / "skills/reviewer"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: reviewer\ndescription: Safe fixture.\n---\nText.\n"
        )
    if control in {"same-stem", "specialist-only"}:
        package["renameSkills"]["reviewer"] = "review-helper"
    elif control == "unused":
        package["renameSkills"]["absent"] = "absent-helper"
    else:
        package["renameSkills"]["help"] = "ordinary-helper"
    (root / "ai-skills.yaml").write_text(dump_document(document))


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
