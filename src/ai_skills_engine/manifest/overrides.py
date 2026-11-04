"""Consumer-owned persisted decisions."""

from dataclasses import dataclass

from ai_skills_engine.manifest.attestation import Attestation
from ai_skills_engine.manifest.collision import Collision
from ai_skills_engine.manifest.migration import Migration
from ai_skills_engine.manifest.record import Record
from ai_skills_engine.registry.ingest_allow import IngestAllow


@dataclass(frozen=True)
class Overrides(Record):
    """Identity migrations, provenance statements and collision decisions."""

    migrations: tuple[Migration, ...] = ()
    attestations: tuple[Attestation, ...] = ()
    collisions: tuple[Collision, ...] = ()
    ingest_allow: tuple[IngestAllow, ...] = ()
