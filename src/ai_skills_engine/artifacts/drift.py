"""Offline manifest and author-input fingerprints recorded by ``ai-skills.lock``."""

import difflib
import sys
from pathlib import Path

from ai_skills_engine.artifacts.format import canonical_json, digest
from ai_skills_engine.inventory.payload import payload_files, source_path
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.registry.safe_tree import walk_files


def manifest_digest(root: Path) -> str:
    """Digest the parsed manifest independently of key order and formatting.

    Args:
        root: Author repository.

    Returns:
        Qualified hash of the canonical JSON encoding of ``ai-skills.yaml``.
    """
    return digest(canonical_json(read_document(root / "ai-skills.yaml")))


def inputs_digest(root: Path) -> str:
    """Commit all local build inputs without fetching any vendor source.

    This is the offline checkout drift gate. Vendor bytes are pinned separately
    by source digests, and a full rebuild compares the actual artifacts. The
    manifest itself is committed by :func:`manifest_digest`; it only selects
    which local payload paths are fingerprinted here.

    Args:
        root: Author repository.

    Returns:
        Qualified hash of declared local payload, legal and builder bytes.
    """
    manifest = read_document(root / "ai-skills.yaml")
    files: dict[str, str] = {}
    for package in manifest.get("packages", []):
        for record in (
            *package.get("capabilities", []),
            *package.get("resources", []),
            *package.get("artifactResources", {}).get("resources", []),
        ):
            source = source_path(root=root, relative=record["path"])
            base = source if source.is_dir() else source.parent
            for item in payload_files(source):
                files[(base / item.path).relative_to(root).as_posix()] = (
                    f"{item.sha256}:{item.mode}"
                )
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "NOTICE.md", "pyproject.toml"):
        if (root / name).is_file():
            files[name] = digest((root / name).read_bytes())
    for directory in ("src/ai_skills_engine", "schemas", "schema"):
        if (root / directory).is_dir():
            for path in walk_files(root=root / directory):
                if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                    continue
                files[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return digest(canonical_json(files))


def report_difference(*, actual: bytes, expected: bytes, label: str) -> None:
    """Print an actionable unified diff between committed and rebuilt bytes.

    Args:
        actual: Committed file bytes.
        expected: Regenerated canonical bytes.
        label: Committed file name.
    """
    sys.stderr.writelines(
        difflib.unified_diff(
            actual.decode("utf-8", errors="replace").splitlines(keepends=True),
            expected.decode("utf-8", errors="replace").splitlines(keepends=True),
            fromfile=label,
            tofile="rebuilt " + label,
        )
    )
