"""Explicit identity migration override."""

from dataclasses import dataclass

from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class Migration(Record):
    """A declared remove/add identity relationship."""

    from_: str
    to: str
