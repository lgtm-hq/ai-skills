"""Resource payload declaration."""

from dataclasses import dataclass

from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class Resource(Record):
    """Named bytes outside capability payload directories."""

    id: str
    path: str
