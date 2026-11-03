"""Serializable deterministic inventory result."""

import json
from dataclasses import dataclass, fields, is_dataclass
from pathlib import PurePath
from typing import Any

from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.capability_id import CapabilityId
from ai_skills_engine.inventory.host_attribute import HostAttribute
from ai_skills_engine.inventory.package_id import PackageId
from ai_skills_engine.inventory.payload_file import PayloadFile
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.inventory.roles import Dialect
from ai_skills_engine.inventory.unresolved_edge import UnresolvedEdge
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.identity import Role

__all__ = [
    "Capability",
    "CapabilityId",
    "Dialect",
    "HostAttribute",
    "Inventory",
    "PackageId",
    "PayloadFile",
    "Resource",
    "ResourceId",
    "Role",
]


def _encode(value: Any) -> Any:
    """Convert records and POSIX paths to plain JSON values.

    Args:
        value: Typed inventory value.

    Returns:
        JSON-compatible representation.
    """
    if isinstance(value, (PackageId, CapabilityId, ResourceId, PurePath)):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _encode(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    return value


@dataclass(frozen=True)
class Inventory:
    """Sorted inventory records and all observed diagnostics, including errors."""

    capabilities: tuple[Capability, ...]
    resources: tuple[Resource, ...]
    diagnostics: tuple[Diagnostic, ...]
    # Evidence comes only from typed declarations/discovery, never diagnostics.
    # Rejected identities have no payload and must never authorize projection.
    rejected: tuple[CapabilityId | ResourceId, ...] = ()
    unresolved_edges: tuple[UnresolvedEdge, ...] = ()

    def to_json(self) -> str:
        """Render deterministic JSON without absolute checkout paths.

        Returns:
            Pretty JSON with stable keys and a trailing newline.
        """
        return (
            json.dumps(_encode(self), indent=2, sort_keys=True, ensure_ascii=True)
            + "\n"
        )
