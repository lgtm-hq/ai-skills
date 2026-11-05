"""Locate observed source bytes through authenticated publication coordinates."""

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.payload import payload_files, source_path
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.provenance.context import origin_locator
from ai_skills_engine.registry.plugin_version import plugin_version


def publications(
    *, root: Path, vendor_roots: Mapping[str, Path]
) -> dict[tuple[str, str | None], tuple[Path, dict[str, Any]]]:
    """Bind supplied snapshots exclusively to manifest pins, including nested pins.

    Args:
        root: Consumer publication.
        vendor_roots: Slash-qualified explicit offline snapshots.

    Returns:
        Publication coordinate to root and consumer-supplied descriptive metadata.

    Raises:
        ValueError: On conflicting roots for the same publication coordinate.
    """
    document = read_document(root / "ai-skills.yaml")
    origin = origin_locator(
        document["publisher"].get("repo", document["publisher"]["id"])
    )
    result: dict[tuple[str, str | None], tuple[Path, dict[str, Any]]] = {
        (origin, None): (root, document)
    }
    pending = [(root, "")]
    seen: set[tuple[Path, str]] = set()
    while pending:
        current, prefix = pending.pop()
        if (current, prefix) in seen:
            continue
        seen.add((current, prefix))
        doc = read_document(current / "ai-skills.yaml")
        for vendor in doc.get("vendors", []):
            alias = prefix + vendor["id"]
            if alias not in vendor_roots:
                continue
            directory = vendor_roots[alias].resolve()
            coordinate = (origin_locator(vendor["repo"]), vendor["sha"])
            existing = result.get(coordinate)
            if (
                existing is not None
                and existing[0] != directory
                and payload_files(existing[0]) != payload_files(directory)
            ):
                raise ValueError("Conflicting snapshots for one pinned publication")
            result[coordinate] = (directory, vendor)
            if (directory / "ai-skills.yaml").is_file():
                pending.append((directory, alias + "/"))
    return result


def record_source(
    *,
    record: Capability | Resource,
    snapshots: Mapping[tuple[str, str | None], tuple[Path, dict[str, Any]]],
) -> Path:
    """Re-observe a matching authenticated payload before using its bytes.

    Args:
        record: Selected inventory record.
        snapshots: Explicit publication roots.

    Returns:
        Safe original file/directory containing exactly the inventoried bytes/modes.

    Raises:
        ValueError: If lineage is missing or no authenticated input matches.
    """
    for chain in record.lineage:
        for hop in reversed(chain.lineage):
            snapshot = snapshots.get((hop.origin, hop.rev))
            if snapshot is None or hop.tree_digest != "sha256:" + record.tree_digest:
                continue
            try:
                source = source_path(root=snapshot[0], relative=hop.path)
                if payload_files(source) == record.payload:
                    return source
            except (OSError, ValueError):
                continue
    raise ValueError(f"No authenticated source bytes for {record.id}")


def identity_assertion(
    *,
    record: Capability | Resource,
    snapshots: Mapping[tuple[str, str | None], tuple[Path, dict[str, Any]]],
) -> dict[str, str]:
    """Mark identities a consumer mapping asserted for a manifestless origin.

    The authority is the record's own origin hop: a pinned origin publication
    without ``ai-skills.yaml`` declared no identities, so the qualified ID came
    from a consumer mapping. Equal bytes or names are never consulted.

    Args:
        record: Selected inventory record with lineage.
        snapshots: Bound publication roots.

    Returns:
        ``{"identity": "consumer-asserted"}`` for mapped records, otherwise empty.
    """
    for chain in record.lineage:
        origin = chain.lineage[0]
        snapshot = snapshots.get((origin.origin, origin.rev))
        if (
            origin.rev is not None
            and snapshot is not None
            and not (snapshot[0] / "ai-skills.yaml").is_file()
        ):
            return {"identity": "consumer-asserted"}
    return {}


def package_version(
    *,
    publisher: str,
    snapshots: Mapping[tuple[str, str | None], tuple[Path, dict[str, Any]]],
) -> str:
    """Use publisher version metadata or a pin-derived package version.

    Args:
        publisher: Qualified package publisher.
        snapshots: Bound publication roots.

    Returns:
        Declared local project version or deterministic pinned version.
    """
    for (_origin, revision), (root, metadata) in sorted(
        snapshots.items(), key=lambda item: (item[0][0], item[0][1] or "")
    ):
        if revision is None:
            if metadata.get("publisher", {}).get("id") != publisher:
                continue
            project = root / "pyproject.toml"
            if project.is_file():
                static_version = (
                    tomllib.loads(project.read_text()).get("project", {}).get("version")
                )
                if static_version is not None:
                    return str(static_version)
            return str(metadata.get("x-version", "0.0.0-local"))
        doc = (
            read_document(root / "ai-skills.yaml")
            if (root / "ai-skills.yaml").is_file()
            else {}
        )
        if (
            metadata.get("id") == publisher
            or doc.get("publisher", {}).get("id") == publisher
        ):
            return plugin_version(
                sha=revision, display_ref=metadata.get("displayRef", "")
            )
    raise ValueError(f"No version input for publisher {publisher}")
