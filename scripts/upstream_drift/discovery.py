"""Discovery of skills that declare an ``upstream`` frontmatter block."""

from __future__ import annotations

from pathlib import Path

import yaml
from skill_frontmatter import split_frontmatter

from upstream_drift.tracked_skill import TrackedSkill

_REQUIRED_FIELDS = ("repo", "path", "version")


def find_tracked_skills(
    skills_root: Path,
) -> list[TrackedSkill]:
    """Collect skills declaring an ``upstream`` frontmatter block.

    Args:
        skills_root: Path to the ``skills/`` directory.

    Returns:
        Tracked skills sorted by skill name.

    Raises:
        ValueError: If a skill's ``upstream`` block is malformed
            (not a mapping, or missing/non-string ``repo``, ``path``,
            or ``version``).
    """
    tracked: list[TrackedSkill] = []
    for skill_dir in sorted(skills_root.iterdir(), key=lambda p: p.name):
        skill_md = skill_dir / "SKILL.md"
        if not skill_dir.is_dir() or not skill_md.is_file():
            continue
        frontmatter_text, _ = split_frontmatter(
            skill_md.read_text(encoding="utf-8"),
        )
        if frontmatter_text is None:
            continue
        frontmatter = yaml.safe_load(frontmatter_text)
        if not isinstance(frontmatter, dict) or "upstream" not in frontmatter:
            continue
        upstream = frontmatter["upstream"]
        if not isinstance(upstream, dict):
            msg = f"{skill_md}: 'upstream' must be a mapping"
            raise ValueError(msg)
        fields: dict[str, str] = {}
        for field in _REQUIRED_FIELDS:
            value = upstream.get(field)
            if not isinstance(value, str) or not value.strip():
                msg = f"{skill_md}: 'upstream.{field}' must be a non-empty string"
                raise ValueError(msg)
            fields[field] = value.strip()
        tracked.append(
            TrackedSkill(
                name=skill_dir.name,
                skill_md=skill_md,
                repo=fields["repo"],
                path=fields["path"],
                version=fields["version"],
            ),
        )
    return tracked
