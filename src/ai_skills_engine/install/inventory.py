"""Merge verified per-package indexes into one inventory, failing closed.

A capability included by several package tars (a cross-package dependency)
must carry identical metadata in each. Every closure entry must name an ID
present in the merged inventory and every capability and resource must carry
lineage. Nothing here computes an edge; it only checks embedded data.
"""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ai_skills_engine.install.deny import lineage_origins
from ai_skills_engine.install.errors import InstallError

type Record = Mapping[str, Any]


@dataclass(frozen=True)
class Inventory:
    """Resolved capability and resource metadata delivered by verified tars.

    Attributes:
        capabilities: Capability records by qualified ID.
        resources: Standalone resource records by qualified ID.
        copies: Every lineage-bearing record of each resource ID, standalone
            or embedded in a capability's ``_shared/`` copy.
        resource_packages: Owning package of each standalone resource.
    """

    capabilities: Mapping[str, Record]
    resources: Mapping[str, Record]
    copies: Mapping[str, tuple[Record, ...]] = field(default_factory=dict)
    resource_packages: Mapping[str, str] = field(default_factory=dict)

    def closure(self, capability: str) -> tuple[frozenset[str], frozenset[str]]:
        """Return a capability's precomputed closure.

        Args:
            capability: Qualified capability ID.

        Returns:
            Capability IDs and resource IDs in its closure.
        """
        closure = self.capabilities[capability]["closure"]
        return frozenset(closure["capabilities"]), frozenset(closure["resources"])


def _canonical(record: Record) -> str:
    """Encode a record for equality checks across tars.

    Args:
        record: Index record.

    Returns:
        Sorted-key JSON.
    """
    return json.dumps(record, sort_keys=True)


def _put(target: dict[str, Record], key: str, record: Record, kind: str) -> None:
    """Insert a record, rejecting a different record under the same ID.

    Args:
        target: Records by ID.
        key: Qualified ID.
        record: Candidate record.
        kind: Record kind for diagnostics.

    Raises:
        InstallError: If two artifacts disagree about the same ID.
    """
    existing = target.get(key)
    if existing is not None and _canonical(existing) != _canonical(record):
        raise InstallError(f"artifacts disagree about {kind} {key}")
    target[key] = record


def _check(inventory: Inventory) -> None:
    """Fail closed on missing lineage or dangling closure entries.

    Args:
        inventory: Merged inventory.

    Raises:
        InstallError: If any embedded fact is missing.
    """
    for key, copies in sorted(inventory.copies.items()):
        for copy in copies:
            lineage_origins(copy["lineage"], subject=key)
    for key, record in sorted(inventory.capabilities.items()):
        lineage_origins(record["lineage"], subject=key)
        capabilities, resources = inventory.closure(key)
        named = (set(record["requires"]) | capabilities) - set(inventory.capabilities)
        named |= resources - set(inventory.copies)
        if named:
            raise InstallError(
                f"{key}: closure names IDs absent from the artifact: "
                + ", ".join(sorted(named))
            )


def merge_indexes(indexes: Iterable[Record]) -> Inventory:
    """Merge per-package indexes from verified tars.

    Args:
        indexes: Schema-valid embedded indexes.

    Returns:
        Checked inventory.
    """
    capabilities: dict[str, Record] = {}
    resources: dict[str, Record] = {}
    owners: dict[str, str] = {}
    copies: dict[str, list[Record]] = {}
    for index in indexes:
        for package in index["packages"]:
            for record in package["capabilities"]:
                _put(capabilities, record["id"], record, "capability")
            for record in package["resources"]:
                _put(resources, record["id"], record, "resource")
                owners[record["id"]] = package["id"]
    for record in resources.values():
        copies.setdefault(record["id"], []).append(record)
    for capability in capabilities.values():
        for record in capability["resources"]:
            copies.setdefault(record["id"], []).append(record)
    inventory = Inventory(
        capabilities=capabilities,
        resources=resources,
        copies={key: tuple(value) for key, value in copies.items()},
        resource_packages=owners,
    )
    _check(inventory)
    return inventory
