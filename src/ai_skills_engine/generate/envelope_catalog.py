"""Bind the artifact index to manifest presentation for envelope generation.

Capabilities, roles, versions and tree digests come only from the artifact
index. The publishing manifest contributes what the index deliberately does
not carry: marketplace membership (explicit exports) and order, display
names, descriptions, authors, declared licenses and in-repo slice paths.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ai_skills_engine.artifact import write_artifacts
from ai_skills_engine.artifacts.format import validate_index
from ai_skills_engine.envelopes import PackageEnvelope, SliceSource
from ai_skills_engine.inventory.payload import payload_files, source_path, tree_digest
from ai_skills_engine.manifest.load import load_manifest
from ai_skills_engine.manifest.model import Manifest
from ai_skills_engine.registry.plugin_manifest import baked_description
from ai_skills_engine.selection.load import load_inputs

_VENDOR_UNAVAILABLE = "selection.vendor-unavailable"


def load_index(path: Path) -> dict[str, Any]:
    """Read and schema-validate a catalog artifact index.

    Args:
        path: ``index.json`` written by ``ai-skills-engine build``.

    Returns:
        Validated index.

    Raises:
        TypeError: If the document is not an object.
    """
    index = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(index, dict):
        raise TypeError(f"Artifact index must be an object: {path}")
    validate_index(index)
    return index


def publisher_index(root: Path) -> dict[str, Any]:
    """Build the publisher's own packages offline and return their index.

    Vendor packages need pinned inputs, so only their availability diagnostic
    is set aside here; every other inventory, selection, provenance and
    ingestion diagnostic still fails the build. A local capability that
    requires an unavailable vendor capability still fails closed. Vendor
    envelopes come from a complete ``ai-skills-engine build`` index instead.

    Args:
        root: Publishing repository.

    Returns:
        Index restricted to the publisher's packages.
    """
    manifest = load_manifest(root / "ai-skills.yaml")
    inventory, selection = load_inputs(root)
    local = replace(
        selection,
        diagnostics=tuple(
            item for item in selection.diagnostics if item.code != _VENDOR_UNAVAILABLE
        ),
    )
    with TemporaryDirectory(prefix="ai-skills-envelopes-") as temporary:
        # The artifact writer refuses symlinked output ancestors; the system
        # temporary directory may sit behind one (macOS /var, a linked TMPDIR).
        destination = Path(temporary).resolve() / "artifacts"
        write_artifacts(
            inventory=inventory,
            selection=local,
            root=root,
            vendor_roots={},
            destination=destination,
        )
        index = json.loads((destination / "index.json").read_text(encoding="utf-8"))
    prefix = manifest.publisher.id + "/"
    index["packages"] = [
        package for package in index["packages"] if package["id"].startswith(prefix)
    ]
    validate_index(index)
    return dict(index)


def _exports(manifest: Manifest) -> set[str]:
    """Qualify explicit exports.

    Args:
        manifest: Publishing manifest.

    Returns:
        Exported package IDs.
    """
    return {
        value if "/" in value else f"{manifest.publisher.id}/{value}"
        for value in manifest.exports
    }


def _author(manifest: Manifest) -> str:
    """Return the publisher author stamped onto first-party envelopes.

    Args:
        manifest: Publishing manifest.

    Returns:
        Repository owner, or the publisher ID without a repository.
    """
    repo = manifest.publisher.repo
    return repo.split("/", maxsplit=1)[0] if repo else manifest.publisher.id


def _slices(
    *, root: Path, manifest: Manifest, package_id: str
) -> dict[str, SliceSource]:
    """Observe each declared in-repo capability tree with inventory hashing.

    Args:
        root: Publishing repository.
        manifest: Publishing manifest.
        package_id: Unqualified local package ID.

    Returns:
        Qualified capability ID to in-repo source, in declaration order.
    """
    package = next(item for item in manifest.packages if item.id == package_id)
    qualified = f"{manifest.publisher.id}/{package.id}"
    return {
        f"{qualified}:{capability.role}/{capability.id}": SliceSource(
            path=capability.path,
            tree_digest="sha256:"
            + tree_digest(
                payload_files(source_path(root=root, relative=capability.path))
            ),
        )
        for capability in package.capabilities
    }


def catalog_packages(
    *, root: Path, include_vendors: bool, slices: bool
) -> list[PackageEnvelope]:
    """Return exported packages in manifest declaration order.

    Args:
        root: Publishing repository.
        include_vendors: Also present exported vendor packages.
        slices: Attach in-repo slice sources to first-party packages.

    Manifest validation already rejects exports that name neither a local
    nor a mapped vendor package.

    Returns:
        Package presentations; none for a repository without a manifest.
    """
    if not (root / "ai-skills.yaml").is_file():
        return []
    manifest = load_manifest(root / "ai-skills.yaml")
    exported = _exports(manifest)
    packages: list[PackageEnvelope] = []
    for package in manifest.packages:
        qualified = f"{manifest.publisher.id}/{package.id}"
        if qualified not in exported:
            continue
        description = package.description or ""
        packages.append(
            PackageEnvelope(
                package=qualified,
                plugin=package.id,
                display_name=package.name or package.id,
                description=description,
                plugin_description=description,
                author=_author(manifest),
                slices=(
                    _slices(root=root, manifest=manifest, package_id=package.id)
                    if slices
                    else None
                ),
            )
        )
    if not include_vendors:
        return packages
    for vendor in manifest.vendors:
        for mapped in (vendor.mapping.packages or ()) if vendor.mapping else ():
            qualified = f"{vendor.id}/{mapped.id}"
            if qualified not in exported:
                continue
            description = mapped.description or ""
            packages.append(
                PackageEnvelope(
                    package=qualified,
                    plugin=mapped.id,
                    display_name=mapped.id,
                    description=description,
                    plugin_description=baked_description(
                        description=description, vendor_id=vendor.id
                    ),
                    author=vendor.repo.split("/", maxsplit=1)[0],
                    license=vendor.license,
                )
            )
    return packages
