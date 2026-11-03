"""Local publication unit."""

from dataclasses import dataclass

from ai_skills_engine.manifest.capability import Capability
from ai_skills_engine.manifest.record import Record
from ai_skills_engine.manifest.resource_record import Resource


@dataclass(frozen=True)
class Package(Record):
    """A package with stable identity, metadata and explicit contents."""

    id: str
    name: str | None = None
    description: str | None = None
    capabilities: tuple[Capability, ...] = ()
    resources: tuple[Resource, ...] = ()
