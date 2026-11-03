"""Frozen inventory capability, distinct from a manifest declaration."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from ai_skills_engine.inventory.capability_id import CapabilityId
from ai_skills_engine.inventory.host_attribute import HostAttribute
from ai_skills_engine.inventory.package_id import PackageId
from ai_skills_engine.inventory.payload_file import PayloadFile
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.inventory.roles import Dialect
from ai_skills_engine.manifest.identity import Role


@dataclass(frozen=True)
class Capability:
    """Observed payload and exclusively declared capability/resource edges."""

    id: CapabilityId
    role: Role
    dialect: Dialect
    package: PackageId
    origin: str
    source_path: PurePosixPath
    payload: tuple[PayloadFile, ...]
    tree_digest: str
    requires: tuple[CapabilityId, ...] = ()
    related: tuple[CapabilityId, ...] = ()
    resources: tuple[ResourceId, ...] = ()
    aliases: tuple[str, ...] = ()
    host_attributes: tuple[HostAttribute, ...] = ()
    destination_names: tuple[str, ...] = ()
