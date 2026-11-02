"""Consumer-owned identity and edges for a manifestless payload."""

from dataclasses import dataclass

from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class MappedCapability(Record):
    """Declarations keyed by a legacy skill name, never inferred dependencies."""

    id: str | None = None
    requires: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
