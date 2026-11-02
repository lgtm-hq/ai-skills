"""Capability payload and declared dependency edges."""

from dataclasses import dataclass

from ai_skills_engine.manifest.identity import Role
from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class Capability(Record):
    """A local payload with stable identity independent of its source path."""

    path: str
    id: str
    role: Role = Role.SKILL
    requires: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
