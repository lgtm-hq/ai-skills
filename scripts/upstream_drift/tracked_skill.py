"""The ``TrackedSkill`` record for upstream-sourced skills."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TrackedSkill:
    """A skill whose content is sourced from an upstream repository.

    Attributes:
        name: Skill directory basename (for example ``design``).
        skill_md: Path to the local SKILL.md file.
        repo: Upstream repository slug (``owner/name``).
        path: Path to the tracked file inside the upstream repository.
        version: Upstream version recorded at last sync.
    """

    name: str
    skill_md: Path
    repo: str
    path: str
    version: str
