"""Deterministic, read-only capability inventory; no selection or projection."""

from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.capability_id import CapabilityId
from ai_skills_engine.inventory.host_attribute import HostAttribute
from ai_skills_engine.inventory.load import load_inventory
from ai_skills_engine.inventory.model import Inventory
from ai_skills_engine.inventory.package_id import PackageId
from ai_skills_engine.inventory.payload_file import PayloadFile
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.inventory.roles import Dialect
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
    "load_inventory",
]
