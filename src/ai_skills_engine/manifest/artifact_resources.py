"""Versioned resource projection delivered only by capability artifacts."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from ai_skills_engine.manifest.record import Record
from ai_skills_engine.manifest.resource_record import Resource


@dataclass(frozen=True)
class ArtifactResources(Record):
    """Explicit resources and complete closures keyed by local role/name."""

    version: Literal[1]
    resources: tuple[Resource, ...] = ()
    bindings: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
