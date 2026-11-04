"""Canonical artifact encoding and installed-resource schema validation."""

import hashlib
import io
import json
import tarfile
from collections.abc import Mapping

# nosemgrep: python37-compatibility-importlib2 - runtime requires Python >=3.13
from importlib import resources
from pathlib import PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from ai_skills_engine.inventory.payload import tree_digest
from ai_skills_engine.inventory.payload_file import PayloadFile
from ai_skills_engine.provenance.ingest import schema as lineage_schema

ARTIFACT_FORMAT = 1
SCHEMA_NAME = "artifact-index.v1.schema.json"
type Files = dict[str, tuple[bytes, int]]


def canonical_json(value: object) -> bytes:
    """Encode stable UTF-8 JSON, including its terminal newline.

    Args:
        value: JSON-compatible value.

    Returns:
        Deterministic serialized bytes.
    """
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    ).encode()


def digest(data: bytes) -> str:
    """Hash bytes with an explicit algorithm prefix.

    Args:
        data: Exact bytes.

    Returns:
        Qualified SHA-256 digest.
    """
    return "sha256:" + hashlib.sha256(data).hexdigest()


def files_digest(files: Mapping[str, tuple[bytes, int]]) -> str:
    """Use inventory's path/hash/canonical-mode identity for an output tree.

    Args:
        files: Relative output paths and their bytes/modes.

    Returns:
        Qualified deterministic tree digest.
    """
    return "sha256:" + tree_digest(
        tuple(
            PayloadFile(path=PurePosixPath(path), sha256=digest(data)[7:], mode=mode)
            for path, (data, mode) in sorted(files.items())
        )
    )


def schema() -> dict[str, Any]:
    """Read format authority shipped in the installed engine.

    Returns:
        Artifact JSON Schema, independent of the author repository.
    """
    return dict(
        json.loads(
            resources.files("ai_skills_engine.data")
            .joinpath(SCHEMA_NAME)
            .read_text(encoding="utf-8")
        )
    )


def validate_index(index: dict[str, Any]) -> None:
    """Validate format and lineage without remote schema resolution.

    Args:
        index: Complete resolved index.

    Raises:
        ValueError: For unsupported formats or malformed metadata.
    """
    lineage = lineage_schema()
    registry: Registry[Any] = Registry().with_resource(
        lineage["$id"], Resource.from_contents(lineage)
    )
    errors = list(Draft202012Validator(schema(), registry=registry).iter_errors(index))
    if errors:
        raise ValueError("Invalid artifact index: " + errors[0].message)


def canonical_tar(files: Files) -> bytes:
    """Write sorted PAX entries with no machine-specific ownership or times.

    Args:
        files: Regular files; every ancestor directory is emitted once.

    Returns:
        Uncompressed tar bytes, the sole artifact identity input.

    Raises:
        ValueError: For unsafe paths, file/directory collisions or invalid modes.
    """
    directories: set[str] = set()
    for path, (_data, mode) in files.items():
        pure = PurePosixPath(path)
        if (
            not path
            or pure.is_absolute()
            or ".." in pure.parts
            or "\\" in path
            or pure.as_posix() != path
            or "\0" in path
            or mode not in {0o644, 0o755}
        ):
            raise ValueError(f"Unsafe artifact entry: {path}")
        directories.update(str(parent) for parent in pure.parents if str(parent) != ".")
    if directories.intersection(files):
        raise ValueError("Artifact file/directory collision")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name in sorted(directories | files.keys()):
            entry = tarfile.TarInfo(name)
            entry.uid = entry.gid = entry.mtime = 0
            entry.uname = entry.gname = ""
            if name in directories:
                entry.type = tarfile.DIRTYPE
                entry.mode = 0o755
                archive.addfile(entry)
            else:
                data, entry.mode = files[name]
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
    return output.getvalue()
