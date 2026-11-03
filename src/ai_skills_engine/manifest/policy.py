"""Consumer policy, never inherited from vendor declarations."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from ai_skills_engine.manifest.deny import Deny
from ai_skills_engine.manifest.identity import Mode, Role, Transport
from ai_skills_engine.manifest.provenance import Provenance
from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class Policy(Record):
    """Selection, provenance and delivery constraints of this consumer."""

    provenance: Provenance | None = None
    deny: Deny | None = None
    roles: tuple[Role, ...] | None = None
    modes: Mapping[str, Mode] = field(default_factory=dict)
    transports: tuple[Transport, ...] | None = None
