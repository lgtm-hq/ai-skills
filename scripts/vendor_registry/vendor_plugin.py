"""Vendor plugin slice declared in the registry."""

from __future__ import annotations

from dataclasses import dataclass

# Top-level names the baker always owns. extraFiles may not use these
# basenames — they would replace skills/, agents/, or generated manifests.
PLUGIN_ROOT_RESERVED_NAMES = frozenset(
    {
        "plugin.json",
        "skills",
        "agents",
        ".claude-plugin",
        ".codex-plugin",
        ".cursor-plugin",
    },
)


@dataclass(frozen=True)
class VendorPlugin:
    """One reviewed plugin slice baked from a vendor repository.

    ``skills`` is ``"*"`` (every skill under ``skills_root``) or a tuple of
    POSIX paths relative to ``skills_root``. ``extra_skills`` are additional
    repo-relative skill directories. ``extra_files`` are additional
    repo-relative files copied to the plugin root (for example a vendor
    README that in-skill docs link to). ``rename_skills`` is an ordered
    mapping of old skill directory names to new names (ADR-0005 class 2).
    ``agents`` are kebab-case agent ``.md`` stems listed in the registry,
    not host ids.
    """

    id: str
    description: str
    skills_root: str
    skills: str | tuple[str, ...]
    extra_skills: tuple[str, ...] = ()
    extra_files: tuple[str, ...] = ()
    rename_skills: tuple[tuple[str, str], ...] = ()
    agents: tuple[str, ...] = ()
