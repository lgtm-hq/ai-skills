"""Reusable deterministic artifact fixtures and byte-level readers."""

import io
import json
import shutil
import tarfile
from pathlib import Path
from typing import Any

import pytest

from ai_skills_engine.artifact import write_artifacts
from ai_skills_engine.artifacts.format import Files
from ai_skills_engine.selection.load import load_inputs

FIXTURE = Path(__file__).parent / "fixtures/artifacts"


@pytest.fixture
def artifact_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy synthetic source inputs and prohibit network use.

    Args:
        tmp_path: Isolated source directory.
        monkeypatch: Offline network guard.

    Returns:
        Fixture publication root.
    """

    def forbidden(*_args: object, **_kwargs: object) -> None:
        """Reject network acquisition in all artifact unit tests."""
        pytest.fail("Artifact tests must remain offline")

    monkeypatch.setattr("socket.socket.connect", forbidden)
    root = tmp_path / "author"
    shutil.copytree(src=FIXTURE / "source", dst=root)
    return root


def bake_fixture(
    *, root: Path, destination: Path, roots: dict[str, Path] | None = None
) -> dict[str, Any]:
    """Build from actual inventory, selection and provenance with pinned builder ID.

    Args:
        root: Source publication.
        destination: Output tree.
        roots: Explicit offline vendor snapshots.

    Returns:
        Reviewed-digest document.
    """
    inventory, selection = load_inputs(root, vendor_roots=roots)
    return write_artifacts(
        inventory=inventory,
        selection=selection,
        root=root,
        vendor_roots=roots or {},
        destination=destination,
        engine_version="0.0.0-fixture",
    )


def tar_files(path: Path) -> Files:
    """Read test-produced regular tar entries without extracting payload code.

    Args:
        path: Canonical tar.

    Returns:
        Relative path to exact bytes and modes.
    """
    files: Files = {}
    with tarfile.open(fileobj=io.BytesIO(path.read_bytes()), mode="r:") as archive:
        for member in archive:
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("Missing regular member payload")
                files[member.name] = (stream.read(), member.mode)
    return files


def index_at(directory: Path) -> dict[str, Any]:
    """Read a generated catalog index.

    Args:
        directory: Artifact directory.

    Returns:
        Resolved index.
    """
    return dict(json.loads((directory / "index.json").read_text()))
