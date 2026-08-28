"""Vendor plugin slice declared in the registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VendorPlugin:
    """One reviewed plugin slice baked from a vendor repository.

    ``skills`` is ``"*"`` (every skill under ``skills_root``) or a tuple of
    POSIX paths relative to ``skills_root``. ``extra_skills`` are additional
    repo-relative paths. ``rename_skills`` is an ordered mapping of old skill
    directory names to new names (ADR-0005 class 2).
    """

    id: str
    description: str
    skills_root: str
    skills: str | tuple[str, ...]
    extra_skills: tuple[str, ...] = ()
    rename_skills: tuple[tuple[str, str], ...] = ()
    agents: tuple[str, ...] = ()
