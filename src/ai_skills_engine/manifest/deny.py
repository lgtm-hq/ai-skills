"""Consumer origin denies."""

from dataclasses import dataclass

from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class Deny(Record):
    """Origins denied anywhere in the provenance chain."""

    origins: tuple[str, ...] = ()
