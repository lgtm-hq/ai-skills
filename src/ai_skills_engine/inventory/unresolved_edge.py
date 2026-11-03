"""Declared edge evidence whose target has no valid payload record."""

from dataclasses import dataclass
from typing import Literal

from ai_skills_engine.inventory.capability_id import CapabilityId


@dataclass(frozen=True)
class UnresolvedEdge:
    """Preserve a declared target separately from diagnostic presentation."""

    source: CapabilityId
    field: Literal["requires", "related", "resources"]
    target: str
