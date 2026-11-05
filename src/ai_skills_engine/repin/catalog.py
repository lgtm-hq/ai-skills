"""Materialize, observe and build one complete catalog for a re-pin side.

Sources are acquired through the lock's source cache (``RESOLVE`` mode: locked
pins must reproduce their digests, changed pins are fetched once). Builds run in
private scratch space; nothing here publishes into the repository.
"""

import hashlib
import io
import json
import tarfile
from collections.abc import Mapping
from pathlib import Path

from ai_skills_engine.artifact import artifact_name
from ai_skills_engine.commands.source_mode import SourceMode
from ai_skills_engine.commands.sources import build_lock, materialize_sources
from ai_skills_engine.inventory.model import Inventory
from ai_skills_engine.lockmodel.lock import Lock
from ai_skills_engine.lockmodel.locked_vendor import LockedVendor
from ai_skills_engine.repin.catalog_side import CatalogSide
from ai_skills_engine.repin.legal_text import content_digest, is_legal, revision_free
from ai_skills_engine.selection.load import load_inputs
from ai_skills_engine.selection.model import SelectionResult
from ai_skills_engine.source_cache import Fetcher, SourceCache


def materialize(
    *,
    root: Path,
    scratch: Path,
    locked: Mapping[str, LockedVendor],
    supplied: Mapping[str, Path] | None = None,
    fetcher: Fetcher | None = None,
) -> tuple[dict[str, Path], tuple[LockedVendor, ...]]:
    """Extract every declared vendor source through the verified cache.

    Args:
        root: Consumer root whose ``ai-skills.yaml`` declares the pins.
        scratch: Private extraction directory.
        locked: Locked vendors by alias; unchanged pins must reproduce them.
        supplied: Explicit offline snapshots by alias.
        fetcher: Acquisition override (tests use a local fake).

    Returns:
        Extracted trees by alias and resolved vendor records.
    """
    return materialize_sources(
        root=root,
        cache=SourceCache.default(),
        scratch=scratch,
        mode=SourceMode.RESOLVE,
        locked=locked,
        supplied=supplied,
        fetcher=fetcher,
    )


def observe(
    *, root: Path, roots: Mapping[str, Path]
) -> tuple[Inventory, SelectionResult]:
    """Plan inventory and selection from extracted sources.

    Args:
        root: Consumer root.
        roots: Extracted vendor trees by alias.

    Returns:
        Inventory and selection of one observation.
    """
    return load_inputs(root, vendor_roots=roots)


def identities(inventory: Inventory) -> tuple[str, ...]:
    """List every observed capability, resource and rejected ID.

    Args:
        inventory: Complete inventory.

    Returns:
        Sorted qualified IDs.
    """
    return tuple(
        sorted(
            {
                *(str(item.id) for item in inventory.capabilities),
                *(str(item.id) for item in inventory.resources),
                *(str(item) for item in inventory.rejected),
            }
        )
    )


def selection_errors(selection: SelectionResult) -> tuple[str, ...]:
    """Render retained selection errors.

    Args:
        selection: Resolver output.

    Returns:
        ``code location: message`` lines, sorted.
    """
    return tuple(
        sorted(
            f"{item.code} {item.location}: {item.message}"
            for item in selection.diagnostics
            if not item.warning
        )
    )


def _artifact_files(
    *, destination: Path, packages: list[str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Hash each package's own members and legal files from its freshly built tar.

    Args:
        destination: Private artifact directory written by this process.
        packages: Package IDs.

    Returns:
        Member path to ``sha256:<hex>:<mode>``, and legal path to its
        revision-free content digest; nothing is extracted.

    Raises:
        ValueError: If a regular member has no payload.
    """
    files: dict[str, str] = {}
    legal: dict[str, list[bytes]] = {}
    for package in packages:
        prefix = f"packages/{package}/"
        data = (destination / artifact_name(package)).read_bytes()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for member in archive:
                owned = member.name.startswith(prefix)
                if not member.isfile() or not (owned or is_legal(member.name)):
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"Missing artifact member payload: {member.name}")
                payload = stream.read()
                if owned:
                    digest = hashlib.sha256(payload).hexdigest()
                    files[member.name] = f"sha256:{digest}:{member.mode:o}"
                else:
                    legal.setdefault(member.name, []).append(
                        revision_free(path=member.name, data=payload)
                    )
    return files, {path: content_digest(items) for path, items in legal.items()}


def build(
    *,
    root: Path,
    roots: Mapping[str, Path],
    vendors: tuple[LockedVendor, ...],
    inputs: tuple[Inventory, SelectionResult],
    destination: Path,
) -> tuple[CatalogSide, Lock]:
    """Build every artifact and describe the result for comparison.

    Args:
        root: Consumer root.
        roots: Extracted vendor trees.
        vendors: Resolved vendor records.
        inputs: Inventory and selection already observed from ``roots``.
        destination: Private artifact directory.

    Returns:
        Comparable catalog and its lock.
    """
    lock = build_lock(
        root=root, roots=roots, vendors=vendors, destination=destination, inputs=inputs
    )
    index = json.loads((destination / "index.json").read_text(encoding="utf-8"))
    files, legal = _artifact_files(
        destination=destination,
        packages=[package["id"] for package in index["packages"]],
    )
    side = CatalogSide(
        index=index,
        files=files,
        artifact_digests={item.id: item.artifact_digest for item in lock.packages},
        legal=legal,
    )
    return side, lock
