"""Effective, consumer-owned ingestion limits (bytes, counts and ratio)."""

from dataclasses import dataclass

from ai_skills_engine.manifest.record import Record


@dataclass(frozen=True)
class IngestLimits(Record):
    """Finite defaults shared by downloads, extraction and selected payloads."""

    download_bytes: int = 100 * 1024 * 1024
    archive_members: int = 20_000
    archive_bytes: int = 500 * 1024 * 1024
    member_bytes: int = 25 * 1024 * 1024
    compression_ratio: int = 100
    file_bytes: int = 5 * 1024 * 1024
    plugin_bytes: int = 50 * 1024 * 1024
    reason: str = ""


DEFAULT_LIMITS = IngestLimits()
