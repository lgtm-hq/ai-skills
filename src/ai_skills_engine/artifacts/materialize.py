"""Self-contained capability copies with resource layout and source diagnostics."""

import json
import os
from collections.abc import Mapping
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlsplit

from ai_skills_engine.artifacts.format import Files, digest, files_digest
from ai_skills_engine.artifacts.references import (
    markdown_body,
    opaque_references,
    resource_path,
    rewrite_fields,
    rewrite_markdown,
)
from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.payload import source_path
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.provenance.model import Lineage
from ai_skills_engine.registry.safe_tree import (
    _local_markdown_path,
    iter_markdown_destinations,
)

_MARKDOWN = frozenset({".md", ".markdown", ".mdc"})


def _destination(target: Path, coordinates: Mapping[Path, str]) -> str | None:
    """Find a declared file or an unambiguous directory's output coordinate.

    Args:
        target: Source-coordinate path.
        coordinates: Declared physical source files and output files.

    Returns:
        File/directory coordinate, or None when not declared or ambiguous.
    """
    if target in coordinates:
        return coordinates[target]
    if not target.is_dir():
        return None
    candidates = set()
    for source, destination in coordinates.items():
        if not source.is_relative_to(target):
            continue
        suffix = source.relative_to(target)
        output = PurePosixPath(destination)
        depth = len(suffix.parts) - 1
        if depth >= len(output.parents):
            return None
        candidate = output.parents[depth]
        if candidate / suffix != output:
            return None
        candidates.add(str(candidate))
    return next(iter(candidates)) if len(candidates) == 1 else None


def _relocate(
    raw: str,
    *,
    original: Path,
    relative: str,
    coordinates: Mapping[Path, str],
) -> str | None:
    """Relocate one operand using declared, observed source coordinates.

    Args:
        raw: Source-coordinate path or URL.
        original: Containing source file.
        relative: Capability-local containing output file.
        coordinates: Declared physical source to output file mapping.

    Returns:
        New operand, or None for remote, unknown or unchanged references.
    """
    local = _local_markdown_path(raw_target=raw)
    if local is None:
        return None
    target = (original.parent / local).resolve()
    mapped = _destination(target, coordinates)
    if mapped is None:
        return None
    moved = os.path.relpath(mapped, start=str(PurePosixPath(relative).parent))
    parts = urlsplit(raw)
    if parts.path.endswith("/") and not moved.endswith("/"):
        moved += "/"  # Keep a directory reference spelled as one.
    rewritten = quote(moved, safe="/.-_~")
    if parts.query:
        rewritten += "?" + parts.query
    if parts.fragment:
        rewritten += "#" + parts.fragment
    return rewritten if rewritten != raw else None


def _declared_path(
    raw: str,
    *,
    original: Path,
    relative: str,
    coordinates: Mapping[Path, str],
    reasons: set[str],
) -> str | None:
    """Record an explicitly declared requirement when its target cannot relocate.

    Args:
        raw: Declared scalar path.
        original: Source file containing it.
        relative: Output file label.
        coordinates: Declared observed payload destinations.
        reasons: Portability diagnostics accumulator.

    Returns:
        Rewritten operand or None to preserve the original bytes.
    """
    local = resource_path(raw)
    if local is None:
        return None
    mapped = _destination((original.parent / local).resolve(), coordinates)
    if mapped is None:
        reasons.add(f"{relative}: declared path is outside payload/required resources")
        return None
    moved = os.path.relpath(mapped, start=str(PurePosixPath(relative).parent))
    if raw.endswith("/") and not moved.endswith("/"):
        moved += "/"  # Keep a directory reference spelled as one.
    return moved if moved != raw else None


def lineage_json(lineage: tuple[Lineage, ...]) -> list[dict[str, Any]]:
    """Keep every authenticated chain and attestation in its published spelling.

    Args:
        lineage: Immutable inventory/selection lineage.

    Returns:
        Deterministically ordered chain records.
    """
    return [
        json.loads(chain.to_json())
        for chain in sorted(lineage, key=lambda item: item.to_json())
    ]


def capability_path(capability: Capability) -> str:
    """Derive an injective artifact path from qualified role identity.

    Args:
        capability: Inventory record.

    Returns:
        POSIX capability root, independent of paths and display names.
    """
    return f"packages/{capability.package}/{capability.role}/{capability.id.name}"


def _observe(
    *,
    record: Capability | Resource,
    source: Path,
    destination: str,
    files: Files,
    coordinates: dict[Path, str],
) -> None:
    """Copy immutable observations without trusting a changed source or symlink.

    Args:
        record: Inventoried payload.
        source: Re-authenticated file/directory.
        destination: Capability-relative destination root or file path.
        files: Output byte/mode accumulator.
        coordinates: Source-file to output-file map.

    Raises:
        ValueError: For changed bytes/modes, undeclared paths or conflicting copies.
    """
    base = source if source.is_dir() else source.parent
    for item in record.payload:
        path = source_path(root=base, relative=str(item.path))
        data = path.read_bytes()
        if (
            digest(data)[7:] != item.sha256
            or (0o755 if path.stat().st_mode & 0o100 else 0o644) != item.mode
        ):
            raise ValueError(f"Source changed during artifact build: {record.id}")
        relative = (
            str(PurePosixPath(destination) / item.path)
            if source.is_dir()
            else destination
        )
        if relative in files and coordinates.get(path) != relative:
            raise ValueError(f"Conflicting artifact resource path: {record.id}")
        files[relative] = (data, item.mode)
        coordinates[path] = relative


def _authenticate_copied(
    *, resource: Resource, source: Path, files: Files, coordinates: dict[Path, str]
) -> None:
    """Check a contained resource's own payload against the bytes already copied.

    Args:
        resource: Selected resource observation.
        source: Its physical root inside the capability source.
        files: Output byte/mode accumulator.
        coordinates: Source-file to output-file map.

    Raises:
        ValueError: If any payload item's bytes or canonical mode differ.
    """
    base = source if source.is_dir() else source.parent
    for item in resource.payload:
        relative = coordinates.get(base / item.path)
        copied = None if relative is None else files[relative]
        if (
            copied is None
            or copied[1] != item.mode
            or digest(copied[0])[7:] != item.sha256
        ):
            raise ValueError(
                f"Source changed during artifact build: contained resource "
                f"{resource.id} differs from its capability copy"
            )


def resource_files(*, resource: Resource, source: Path) -> Files:
    """Retain standalone resources, including packages containing only resources.

    Args:
        resource: Selected resource observation.
        source: Re-authenticated resource source.

    Returns:
        Unmodified resource-relative bytes and canonical modes.
    """
    files: Files = {}
    _observe(
        record=resource,
        source=source,
        destination="." if source.is_dir() else source.name,
        files=files,
        coordinates={},
    )
    return files


def materialize(
    *,
    capability: Capability,
    source: Path,
    resources: tuple[tuple[Resource, Path], ...],
) -> tuple[Files, list[dict[str, Any]], list[dict[str, str]]]:
    """Copy explicit requirements and rewrite only structurally proven references.

    Args:
        capability: Selected capability.
        source: Safe observed source payload.
        resources: Its selected, declared resource records and physical roots.

    Returns:
        Capability-relative files, per-copy resource records and portability losses.

    Raises:
        ValueError: On collisions, missing declared files or changed source bytes.
    """
    files: Files = {}
    coordinates: dict[Path, str] = {}
    base = source if source.is_dir() else source.parent
    _observe(
        record=capability,
        source=source,
        destination="." if source.is_dir() else source.name,
        files=files,
        coordinates=coordinates,
    )
    copies: list[tuple[Resource, str, Path]] = []
    declarations = dict.fromkeys(capability.resource_paths)
    for resource, original in resources:
        if original == source or (source.is_dir() and original.is_relative_to(source)):
            destination = original.relative_to(base).as_posix()
            _authenticate_copied(
                resource=resource,
                source=original,
                files=files,
                coordinates=coordinates,
            )
        else:
            destination = (
                f"_shared/{resource.id.package.publisher}/{resource.source_path}"
            )
            _observe(
                record=resource,
                source=original,
                destination=destination,
                files=files,
                coordinates=coordinates,
            )
        copies.append((resource, destination, original))
        for file, pointer in resource.resource_paths:
            target = (
                str(PurePosixPath(destination) / file)
                if original.is_dir()
                else destination
            )
            declarations[target, pointer] = None
    if any(file not in files for file, _pointer in declarations):
        raise ValueError(f"Declared resource path file is absent: {capability.id}")
    reasons: set[str] = set()
    directories = {
        str(parent) for path in files for parent in PurePosixPath(path).parents
    }
    for original, relative in sorted(coordinates.items(), key=lambda pair: pair[1]):
        data, mode = files[relative]
        if b"\0" in data[:8192]:
            if any(file == relative for file, _ in declarations):
                reasons.add(f"{relative}: declared resource path in binary content")
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            if any(file == relative for file, _ in declarations):
                reasons.add(f"{relative}: declared path in non-UTF-8 content")
            continue

        relocate = partial(
            _relocate, original=original, relative=relative, coordinates=coordinates
        )

        markdown = Path(relative).suffix.lower() in _MARKDOWN
        pointers = tuple(pointer for file, pointer in declarations if file == relative)
        try:
            if markdown:
                for raw in iter_markdown_destinations(text=markdown_body(text)[1]):
                    local = _local_markdown_path(raw_target=raw)
                    if (
                        local is not None
                        and _destination(
                            (original.parent / local).resolve(), coordinates
                        )
                        is None
                    ):
                        reasons.add(
                            f"{relative}: unresolved capability-local "
                            "Markdown reference"
                        )
            if pointers:
                text = rewrite_fields(
                    text=text,
                    pointers=pointers,
                    markdown=markdown,
                    replace=partial(
                        _declared_path,
                        original=original,
                        relative=relative,
                        coordinates=coordinates,
                        reasons=reasons,
                    ),
                )
            if markdown:
                text = rewrite_markdown(text=text, replace=relocate)
            if opaque_references(text=text, replace=relocate):
                reasons.add(
                    f"{relative}: reference outside structurally understood fields"
                )
        except (ValueError, TypeError) as error:
            reasons.add(
                f"{relative}: {type(error).__name__} in structural resource reference"
            )
        files[relative] = (text.encode(), mode)
        if markdown:
            for raw in iter_markdown_destinations(text=markdown_body(text)[1]):
                try:
                    local = _local_markdown_path(raw_target=raw)
                    if local is None:
                        continue
                    # Pure path normalization is independent of the build directory.
                    target = os.path.normpath(
                        str(PurePosixPath(relative).parent / local)
                    )
                    if target not in files and target not in directories:
                        reasons.add(
                            f"{relative}: unresolved capability-local "
                            "Markdown reference"
                        )
                except ValueError:
                    reasons.add(f"{relative}: unsafe Markdown reference")
    records = []
    for resource, destination, original in copies:
        resource_base = original if original.is_dir() else original.parent
        observed = {
            str(item.path): files[coordinates[resource_base / item.path]]
            for item in resource.payload
        }
        records.append(
            {
                "id": str(resource.id),
                "path": destination,
                "treeDigest": files_digest(observed),
                "sourceTreeDigest": "sha256:" + resource.tree_digest,
                "lineage": lineage_json(resource.lineage),
            }
        )
    portability = [
        {"mode": mode, "state": "source-unportable", "reason": reason}
        for mode in ("user-explode", "repo-materialize")
        for reason in sorted(reasons)
    ]
    return (
        files,
        sorted(records, key=lambda item: (item["id"], item["path"])),
        portability,
    )
