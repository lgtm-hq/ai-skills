"""Load artifact indexes and validate them against the packaged JSON Schema.

The format number is checked first so an unknown ``artifactFormat`` gets its
own diagnostic. Every other shape rule, including unknown fields, comes from
``artifact-index.v1.schema.json`` and the lineage schema it references.
"""

import io
import json
import tarfile
from functools import cache

# nosemgrep: python37-compatibility-importlib2 - runtime requires Python >=3.13
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from ai_skills_engine.install.errors import InstallError
from ai_skills_engine.install.strict_json import load_object

ARTIFACT_FORMAT = 1
INDEX_NAME = "index.json"
_INDEX_SCHEMA = ("ai_skills_engine.data", "artifact-index.v1.schema.json")
_LINEAGE_SCHEMA = ("ai_skills_engine.provenance", "lineage.v1.schema.json")


def _packaged_schema(package: str, name: str) -> dict[str, Any]:
    """Read a schema shipped inside the installed engine.

    Args:
        package: Package that owns the resource.
        name: Resource file name.

    Returns:
        Decoded JSON Schema.
    """
    text = resources.files(package).joinpath(name).read_text(encoding="utf-8")
    return dict(json.loads(text))


@cache
def _validator() -> Draft202012Validator:
    """Build the offline index validator once per process.

    Returns:
        Validator that resolves the lineage schema locally.
    """
    lineage = _packaged_schema(*_LINEAGE_SCHEMA)
    registry: Registry[Any] = Registry().with_resource(
        lineage["$id"], Resource.from_contents(lineage)
    )
    return Draft202012Validator(_packaged_schema(*_INDEX_SCHEMA), registry=registry)


def parse_index(data: bytes, *, source: str) -> dict[str, Any]:
    """Decode and validate one artifact index.

    Args:
        data: Exact ``index.json`` bytes.
        source: Label used in diagnostics.

    Returns:
        Schema-valid index.

    Raises:
        InstallError: For malformed JSON, an unknown format or any schema error.
    """
    index = load_object(data, source=source)
    found = index.get("artifactFormat")
    if found != ARTIFACT_FORMAT or isinstance(found, bool):
        raise InstallError(
            f"{source}: unsupported artifactFormat {json.dumps(found)}; "
            f"this engine reads artifactFormat {ARTIFACT_FORMAT}"
        )
    errors = sorted(_validator().iter_errors(index), key=lambda item: item.json_path)
    if errors:
        first = errors[0]
        raise InstallError(
            f"{source}: invalid index at {first.json_path}: {first.message}"
        )
    return index


def load_catalog(directory: Path) -> dict[str, Any]:
    """Read the catalog index at the root of an artifact directory.

    Args:
        directory: Artifact directory containing ``index.json`` and tars.

    Returns:
        Schema-valid catalog index.

    Raises:
        InstallError: If the index is missing or invalid.
    """
    path = directory / INDEX_NAME
    if not path.is_file():
        raise InstallError(f"no artifact index at {path}")
    return parse_index(path.read_bytes(), source=str(path))


def embedded_index(tar: bytes, *, package: str) -> dict[str, Any]:
    """Read the index a verified package tar carries, without extracting files.

    Args:
        tar: Verified uncompressed tar bytes.
        package: Package the tar must declare as its root.

    Returns:
        Schema-valid per-package index.

    Raises:
        InstallError: If the tar has no single regular index or names another root.
    """
    label = f"{package} artifact {INDEX_NAME}"
    try:
        with tarfile.open(fileobj=io.BytesIO(tar), mode="r:") as archive:
            members = [item for item in archive if item.name == INDEX_NAME]
            if len(members) != 1 or not members[0].isfile():
                raise InstallError(f"{label}: expected exactly one regular file")
            stream = archive.extractfile(members[0])
            data = stream.read() if stream is not None else b""
    except tarfile.TarError as error:
        raise InstallError(f"{package} artifact: unreadable tar ({error})") from error
    index = parse_index(data, source=label)
    if index["rootPackage"] != package:
        raise InstallError(
            f"{label}: rootPackage {index['rootPackage']!r} is not {package!r}"
        )
    return index


def artifact_name(package: str) -> str:
    """Map a qualified package ID to its transport filename.

    Args:
        package: Qualified ``publisher/package`` ID.

    Returns:
        ``publisher--package.tar``, matching the build plane's encoding.
    """
    return package.replace("/", "--") + ".tar"
