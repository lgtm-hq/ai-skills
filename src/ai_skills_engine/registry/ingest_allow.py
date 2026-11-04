"""One consumer-owned, digest-bound content acknowledgement."""

from dataclasses import dataclass

from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class IngestAllow(Record):
    """Acknowledge one rule at one original repository path and file digest."""

    path: str
    rule: str
    sha256: str
    reason: str
