"""Publisher identity declaration."""

from dataclasses import dataclass

from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class Publisher(Record):
    """Stable publisher identity and optional transport locator."""

    id: str
    repo: str | None = None
