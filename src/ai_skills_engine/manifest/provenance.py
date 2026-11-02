"""Consumer provenance policy."""

from dataclasses import dataclass
from typing import Literal

from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class Provenance(Record):
    """Strictness and consumer acceptance of independently authored attestations."""

    mode: Literal["strict", "warn"]
    accept_attestations: bool = False
