"""Independently authored provenance override."""

from dataclasses import dataclass
from typing import Literal

from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class Attestation(Record):
    """Consumer statement which does not erase known lineage."""

    capability: str
    path: str
    independently_authored: Literal[True]
    reason: str
