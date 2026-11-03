"""Consumer mapping for a vendor without its own manifest."""

from dataclasses import dataclass

from ai_skills_engine.manifest.mapped_package import MappedPackage
from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class VendorMapping(Record):
    """Legacy discovery roots and reviewed package slices."""

    skill_roots: tuple[str, ...]
    packages: tuple[MappedPackage, ...] | None = None
