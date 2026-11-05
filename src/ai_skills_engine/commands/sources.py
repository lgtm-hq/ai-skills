"""Materialize locked or resolvable vendor sources and regenerate the lock."""

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ai_skills_engine import artifact
from ai_skills_engine.artifacts.drift import inputs_digest, manifest_digest
from ai_skills_engine.artifacts.format import ARTIFACT_FORMAT
from ai_skills_engine.bake import vendor_plugins
from ai_skills_engine.commands.source_mode import SourceMode
from ai_skills_engine.inventory.model import Inventory
from ai_skills_engine.lockfile import LOCK_HINT, StaleLockError
from ai_skills_engine.lockmodel.builder import Builder
from ai_skills_engine.lockmodel.filters import Filters
from ai_skills_engine.lockmodel.lock import Lock
from ai_skills_engine.lockmodel.locked_capability import LockedCapability
from ai_skills_engine.lockmodel.locked_package import LockedPackage
from ai_skills_engine.lockmodel.locked_resource import LockedResource
from ai_skills_engine.lockmodel.locked_vendor import LockedVendor
from ai_skills_engine.lockmodel.manifest_record import ManifestRecord
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.registry.ingest_checks import parse_limits
from ai_skills_engine.registry.ingest_limits import IngestLimits
from ai_skills_engine.registry.vendor import Vendor
from ai_skills_engine.selection.load import load_inputs
from ai_skills_engine.selection.model import SelectionResult
from ai_skills_engine.source_cache import (
    Fetcher,
    SourceCache,
    canonical_snapshot,
    extract_canonical,
    materialize,
)

_MAX_DEPTH = 64


def _fetcher() -> Fetcher:
    """Return the bounded GitHub fetcher, resolved at call time.

    Returns:
        Keyword ``(vendor=, dest=)`` acquisition function.
    """
    return lambda **kwargs: vendor_plugins._fetch_vendor_tree(**kwargs)


def _vendor(entry: Mapping[str, Any], alias: str) -> Vendor:
    """Build the acquisition record for one manifest vendor entry.

    Args:
        entry: Manifest vendor declaration.
        alias: Slash-qualified consumer alias.

    Returns:
        Registry vendor carrying the pin and its ingestion limits.
    """
    return Vendor(
        id=alias,
        repo=entry["repo"],
        sha=entry["sha"],
        skill_roots=(),
        license=entry.get("license", ""),
        homepage=entry.get("homepage", ""),
        ingest_limits=(
            parse_limits(entry["ingestLimits"], label=alias)
            if "ingestLimits" in entry
            else IngestLimits()
        ),
    )


def materialize_sources(
    *,
    root: Path,
    cache: SourceCache,
    scratch: Path,
    mode: SourceMode,
    locked: Mapping[str, LockedVendor],
    supplied: Mapping[str, Path] | None = None,
    fetcher: Fetcher | None = None,
) -> tuple[dict[str, Path], tuple[LockedVendor, ...]]:
    """Walk declared pins, including nested pins, and extract verified sources.

    Unchanged pins (same repo, SHA and filters as the lock) must reproduce
    their locked source digest. Changed or new pins are resolved only in
    ``RESOLVE`` mode. ``FROZEN`` mode never acquires or writes anything.

    Args:
        root: Consumer manifest root.
        cache: Source cache.
        scratch: Private directory receiving extracted trees.
        mode: Acquisition authority.
        locked: Locked vendors by alias.
        supplied: Explicit offline snapshots by alias (``RESOLVE``/``FETCH``).
        fetcher: Acquisition override; defaults to the bounded GitHub fetcher.

    Returns:
        Extracted trees by alias and the resolved vendor records.

    Raises:
        StaleLockError: When a frozen operation meets an unlocked pin.
        ValueError: For recursive imports or unknown supplied aliases.
    """
    explicit = dict(supplied or {})
    acquire = None if mode is SourceMode.FROZEN else (fetcher or _fetcher())
    roots: dict[str, Path] = {}
    records: list[LockedVendor] = []
    pending: list[tuple[Path, str, tuple[tuple[str, str], ...]]] = [(root, "", ())]
    while pending:
        current, prefix, ancestors = pending.pop(0)
        for entry in read_document(current / "ai-skills.yaml").get("vendors", []):
            identity = (entry["repo"], entry["sha"])
            if identity in ancestors or len(ancestors) >= _MAX_DEPTH:
                raise ValueError("Recursive pinned artifact input")
            alias = prefix + entry["id"]
            filters = Filters(
                include=tuple(entry.get("include", ())),
                exclude=tuple(entry.get("exclude", ())),
            )
            previous = locked.get(alias)
            unchanged = previous is not None and (
                previous.repo,
                previous.sha,
                previous.filters,
            ) == (*identity, filters)
            if not unchanged and mode is not SourceMode.RESOLVE:
                if mode is SourceMode.FETCH:
                    print(
                        f"lock: vendor {alias} ({identity[0]}@{identity[1]}) is not "
                        f"in ai-skills.lock; skipped; {LOCK_HINT}",
                        file=sys.stderr,
                    )
                    explicit.pop(alias, None)
                    continue
                raise StaleLockError(
                    f"ai-skills.lock is stale: vendor {alias} "
                    f"({identity[0]}@{identity[1]}) is not locked; {LOCK_HINT}"
                )
            expected = previous.source_digest if unchanged and previous else None
            vendor = _vendor(entry, alias)
            destination = scratch / str(len(roots))
            if alias in explicit:
                data = canonical_snapshot(tree=explicit.pop(alias), vendor=vendor)
                digest = cache.store(
                    data=data,
                    repo=vendor.repo,
                    revision=vendor.sha,
                    label=alias,
                    expected=expected,
                )
                extract_canonical(data=data, dest=destination)
            else:
                digest = materialize(
                    cache=cache,
                    vendor=vendor,
                    dest=destination,
                    fetcher=acquire,
                    expected=expected,
                )
            roots[alias] = destination
            records.append(
                LockedVendor(
                    id=alias,
                    repo=vendor.repo,
                    sha=vendor.sha,
                    source_digest=digest,
                    filters=filters,
                )
            )
            if (destination / "ai-skills.yaml").is_file():
                pending.append((destination, alias + "/", (*ancestors, identity)))
    if explicit:
        raise ValueError(f"Unknown --vendor-root aliases: {sorted(explicit)}")
    undeclared = sorted(set(locked) - set(roots))
    if undeclared and mode is SourceMode.FROZEN:
        raise StaleLockError(
            "ai-skills.lock is stale: it locks undeclared vendor(s) "
            f"{', '.join(undeclared)}; {LOCK_HINT}"
        )
    return roots, tuple(sorted(records, key=lambda item: item.id))


def current_builder() -> Builder:
    """Identify the installed builder.

    Returns:
        Installed engine version and supported artifact format.
    """
    return Builder(
        engine_version=artifact.installed_engine_version(),
        artifact_format=ARTIFACT_FORMAT,
    )


def check_current(*, root: Path, lock: Lock) -> None:
    """Reject a lock that no longer matches the builder, manifest or local inputs.

    This offline check needs no vendor source.

    Args:
        root: Consumer manifest root.
        lock: Strictly parsed lock.

    Raises:
        StaleLockError: With a message naming the stale component.
    """
    builder = current_builder()
    if lock.builder != builder:
        raise StaleLockError(
            "ai-skills.lock is stale: it was built by engine "
            f"{lock.builder.engine_version} (artifactFormat "
            f"{lock.builder.artifact_format}), this engine is "
            f"{builder.engine_version} (artifactFormat {builder.artifact_format}); "
            + LOCK_HINT
        )
    document = read_document(root / "ai-skills.yaml")
    digest = manifest_digest(root)
    if lock.manifest.digest != digest or lock.manifest.api_version != document.get(
        "apiVersion"
    ):
        raise StaleLockError(
            "ai-skills.lock is stale: the ai-skills.yaml manifest digest changed "
            f"(locked {lock.manifest.digest}, current {digest}); " + LOCK_HINT
        )
    local = inputs_digest(root)
    if lock.manifest.inputs_digest != local:
        raise StaleLockError(
            "ai-skills.lock is stale: local author inputs changed (locked "
            f"{lock.manifest.inputs_digest}, current {local}); " + LOCK_HINT
        )


def build_lock(
    *,
    root: Path,
    roots: Mapping[str, Path],
    vendors: tuple[LockedVendor, ...],
    destination: Path,
    inputs: tuple[Inventory, SelectionResult] | None = None,
) -> Lock:
    """Build every artifact from extracted sources and describe it as a lock.

    Capability closure, lineage and standalone resources (including
    artifact-only resources) are read from the built index, never inferred.

    Args:
        root: Consumer manifest root.
        roots: Extracted vendor trees by alias.
        vendors: Resolved vendor records.
        destination: New artifact directory (installed atomically).
        inputs: Inventory and selection already observed from ``roots``.

    Returns:
        Regenerated lock.
    """
    inventory, selection = inputs or load_inputs(root, vendor_roots=roots)
    result = artifact.write_artifacts(
        inventory=inventory,
        selection=selection,
        root=root,
        vendor_roots=roots,
        destination=destination,
    )
    index = json.loads((destination / "index.json").read_text(encoding="utf-8"))
    packages = tuple(
        LockedPackage(
            id=package["id"],
            version=package["version"],
            artifact_digest=result["packages"][package["id"]]["artifactDigest"],
            tree_digest=package["treeDigest"],
            capabilities=tuple(
                LockedCapability(
                    id=item["id"],
                    closure=tuple(
                        sorted(
                            {
                                *item["closure"]["capabilities"],
                                *item["closure"]["resources"],
                            }
                        )
                    ),
                    lineage=tuple(item["lineage"]),
                )
                for item in package["capabilities"]
            ),
            resources=tuple(
                LockedResource(id=item["id"], lineage=tuple(item["lineage"]))
                for item in package["resources"]
            ),
        )
        for package in index["packages"]
    )
    return Lock(
        builder=Builder(
            engine_version=index["engineVersion"],
            artifact_format=index["artifactFormat"],
        ),
        manifest=ManifestRecord(
            api_version=index["apiVersion"],
            digest=manifest_digest(root),
            inputs_digest=inputs_digest(root),
        ),
        vendors=vendors,
        packages=packages,
    )
