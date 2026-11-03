"""Pinned vendor import declaration."""

from dataclasses import dataclass

from ai_skills_engine.manifest.mapping import VendorMapping
from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class Vendor(Record):
    """Import metadata and consumer-owned selection; no vendor trust grants."""

    id: str
    repo: str
    sha: str
    display_ref: str | None = None
    branch: str | None = None
    license: str | None = None
    homepage: str | None = None
    mapping: VendorMapping | None = None
    include: tuple[str, ...] | None = None
    exclude: tuple[str, ...] | None = None
