"""Persisted consumer collision answer."""

from dataclasses import dataclass
from typing import Literal

from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class Collision(Record):
    """Keep, rename or skip a capability; rename requires a destination name."""

    capability: str
    action: Literal["keep", "rename", "skip"]
    name: str | None = None
