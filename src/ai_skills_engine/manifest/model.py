"""Frozen typed representation of the published v1 JSON Schema."""

from dataclasses import dataclass
from typing import Literal

from ai_skills_engine.manifest.overrides import Overrides
from ai_skills_engine.manifest.package import Package
from ai_skills_engine.manifest.policy import Policy
from ai_skills_engine.manifest.publisher import Publisher
from ai_skills_engine.manifest.record import Record
from ai_skills_engine.manifest.vendor import Vendor


@dataclass(frozen=True)
class Manifest(Record):
    """One repository's publication, imports, exports and consumer policy."""

    api_version: Literal["ai-skills.dev/v1"]
    publisher: Publisher
    packages: tuple[Package, ...] = ()
    vendors: tuple[Vendor, ...] = ()
    exports: tuple[str, ...] = ()
    policy: Policy | None = None
    overrides: Overrides | None = None
