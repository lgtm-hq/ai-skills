"""Vendor registry record."""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_skills_engine.registry.ingest_allow import IngestAllow
from ai_skills_engine.registry.ingest_limits import IngestLimits
from ai_skills_engine.registry.vendor_plugin import VendorPlugin


@dataclass(frozen=True)
class Vendor:
    """One SHA-pinned third-party skill vendor.

    ``display_ref`` is the optional consumer-facing pin (``displayRef``).
    Bake uses it as the plugin version when it is a tag; floating pins
    such as ``latest`` fall back to the short SHA.
    ``branch`` optionally selects the upstream heads ref for automated repins.
    """

    id: str
    repo: str
    sha: str
    skill_roots: tuple[str, ...]
    license: str
    homepage: str
    display_ref: str | None = None
    plugins: tuple[VendorPlugin, ...] = ()
    branch: str | None = None
    ingest_allow: tuple[IngestAllow, ...] = ()
    ingest_limits: IngestLimits = field(default_factory=IngestLimits)
