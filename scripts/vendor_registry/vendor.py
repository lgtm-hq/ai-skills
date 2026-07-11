"""Vendor registry record."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Vendor:
    """One SHA-pinned third-party skill vendor."""

    id: str
    repo: str
    sha: str
    skill_roots: tuple[str, ...]
    license: str
    homepage: str
