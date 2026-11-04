"""Generated digest commitments and offline author-input drift checks."""

import difflib
import json
import sys
from pathlib import Path
from typing import Any

from ai_skills_engine.artifacts.format import ARTIFACT_FORMAT, canonical_json, digest
from ai_skills_engine.inventory.payload import payload_files, source_path
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.registry.registry import load_unique_yaml_text
from ai_skills_engine.registry.safe_tree import walk_files


def inputs_digest(root: Path) -> str:
    """Commit all local build inputs and pinned vendor declarations without fetching.

    This is the checkout drift gate; publishing additionally rebuilds all package
    trees and compares their actual tar and tree identities. Vendor bytes never
    become trusted merely because this local input fingerprint matches.

    Args:
        root: Author repository.

    Returns:
        Qualified hash of explicit manifest, local payload, legal and builder bytes.
    """
    manifest = read_document(root / "ai-skills.yaml")
    files = {"ai-skills.yaml": digest((root / "ai-skills.yaml").read_bytes())}
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


def read_digests(path: Path) -> dict[str, Any]:
    """Read a versioned commitment with duplicate-key and digest-shape checks.

    Args:
        path: Committed generated file.

    Returns:
        Parsed commitment.

    Raises:
        ValueError: On unknown format, malformed values or duplicate keys.
    """
    text = path.read_text(encoding="utf-8")
    json.loads(text)
    data = load_unique_yaml_text(text=text, source=path.name)
    if (
        not isinstance(data, dict)
        or type(data.get("artifactFormat")) is not int
        or data.get("artifactFormat") != ARTIFACT_FORMAT
        or set(data) != {"artifactFormat", "inputsDigest", "packages"}
        or not isinstance(data["packages"], dict)
    ):
        raise ValueError("Unsupported artifact digest commitment")
    import re

    values = [data["inputsDigest"]]
    for package, entry in data["packages"].items():
        if (
            not isinstance(package, str)
            or not isinstance(entry, dict)
            or set(entry) != {"treeDigest", "artifactDigest"}
        ):
            raise ValueError("Invalid artifact digest package record")
        values.extend(entry.values())
    if any(
        not isinstance(value, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
        for value in values
    ):
        raise ValueError("Invalid artifact digest")
    return dict(data)


def compare_digests(*, expected: dict[str, Any], path: Path) -> bool:
    """Compare a rebuild with the reviewed file and print an actionable diff.

    Args:
        expected: Actual regenerated document.
        path: Committed generated file.

    Returns:
        True only for canonical byte equality.
    """
    actual = path.read_text() if path.is_file() else ""
    rendered = canonical_json(expected).decode()
    if actual == rendered:
        return True
    sys.stderr.writelines(
        difflib.unified_diff(
            actual.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=str(path),
            tofile="rebuilt artifact digests",
        )
    )
    return False


def check_inputs(*, root: Path, path: Path) -> bool:
    """Check a fresh clone offline; the publish gate also verifies vendor output.

    Args:
        root: Author repository.
        path: Reviewed generated commitment.

    Returns:
        Whether canonical commitment and all local build inputs remain current.
    """
    data = read_digests(path)
    return compare_digests(
        expected={**data, "inputsDigest": inputs_digest(root)}, path=path
    )
