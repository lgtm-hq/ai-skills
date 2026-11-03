"""Lossless consumer-owned mapping of legacy plugin slices."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from ai_skills_engine.manifest.mapped_capability import MappedCapability
from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class MappedPackage(Record):
    """All legacy slice fields plus explicit per-name capability declarations."""

    id: str
    skills_root: str
    skills: Literal["*"] | tuple[str, ...]
    description: str | None = None
    extra_skills: tuple[str, ...] | None = None
    extra_files: tuple[str, ...] | None = None
    rename_skills: Mapping[str, str] | None = None
    agents: tuple[str, ...] | None = None
    capabilities: Mapping[str, MappedCapability] = field(default_factory=dict)
