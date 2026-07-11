#!/usr/bin/env python3
"""Validate ``skills/*/SKILL.md`` frontmatter values.

Single Python parser replacing the awk key-presence grep in
``scripts/validate.sh``. For every skill it checks that:

- the frontmatter parses as a YAML mapping (CRLF-normalized, closing
  ``---`` present),
- ``name`` and ``description`` are non-empty strings (YAML lists or
  mappings are rejected),
- ``description`` is at most 1024 characters (Claude Code's
  skill-loading limit),
- ``name`` equals the skill directory basename.

Prints one line per violation (including the file path) and exits 1 on
any violation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from skill_frontmatter import split_frontmatter

DESCRIPTION_MAX_LENGTH = 1024


def _validate_string_field(
    frontmatter: dict[str, object],
    field: str,
    skill_md: Path,
) -> tuple[str | None, list[str]]:
    """Validate that a frontmatter field is a non-empty string.

    Args:
        frontmatter: Parsed frontmatter mapping.
        field: Key to validate (for example ``name``).
        skill_md: Path to the SKILL.md file, used in violation messages.

    Returns:
        A tuple ``(value, violations)`` where ``value`` is the validated
        string (or ``None`` if invalid) and ``violations`` is a list of
        human-readable violation messages.
    """
    value = frontmatter.get(field)
    if value is None:
        return None, [f"{skill_md}: missing '{field}' in frontmatter"]
    if not isinstance(value, str):
        return None, [
            f"{skill_md}: '{field}' must be a string, got {type(value).__name__}",
        ]
    if not value.strip():
        return None, [f"{skill_md}: '{field}' must be a non-empty string"]
    return value, []


def validate_skill(
    skill_md: Path,
) -> list[str]:
    """Validate one SKILL.md file's frontmatter values.

    Args:
        skill_md: Path to ``SKILL.md`` under ``skills/<id>/``.

    Returns:
        A list of violation messages; empty when the file is valid.
    """
    try:
        text = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{skill_md}: cannot read file: {exc}"]
    frontmatter_text, _ = split_frontmatter(text)
    if frontmatter_text is None:
        return [f"{skill_md}: missing opening/closing --- frontmatter delimiters"]
    try:
        frontmatter = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        return [f"{skill_md}: frontmatter is not valid YAML: {exc}"]
    if not isinstance(frontmatter, dict):
        return [
            f"{skill_md}: frontmatter must be a YAML mapping, "
            f"got {type(frontmatter).__name__}",
        ]
    violations: list[str] = []
    name, name_violations = _validate_string_field(
        frontmatter=frontmatter,
        field="name",
        skill_md=skill_md,
    )
    violations.extend(name_violations)
    description, desc_violations = _validate_string_field(
        frontmatter=frontmatter,
        field="description",
        skill_md=skill_md,
    )
    violations.extend(desc_violations)
    if description is not None and len(description) > DESCRIPTION_MAX_LENGTH:
        violations.append(
            f"{skill_md}: 'description' is {len(description)} characters, "
            f"exceeds the {DESCRIPTION_MAX_LENGTH}-character limit",
        )
    directory_name = skill_md.parent.name
    if name is not None and name != directory_name:
        violations.append(
            f"{skill_md}: 'name' {name!r} does not match "
            f"directory name {directory_name!r}",
        )
    return violations


def validate_skills_tree(
    skills_root: Path,
) -> list[str]:
    """Validate every ``skills/*/SKILL.md`` under a skills root.

    Args:
        skills_root: Path to the ``skills/`` directory.

    Returns:
        A list of violation messages across all skills; empty when all
        skills are valid.
    """
    violations: list[str] = []
    for skill_dir in sorted(skills_root.iterdir(), key=lambda p: p.name):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            # Presence is checked by validate.sh; nothing to parse here.
            continue
        violations.extend(
            validate_skill(skill_md=skill_md),
        )
    return violations


def main() -> int:
    """Validate frontmatter values for all skills under a skills root.

    When invoked from ``validate.sh``, the skills root is passed explicitly
    so frontmatter checks use the same cwd-relative tree as the shell checks.
    When run directly, defaults to ``skills`` in the current directory.

    Returns:
        Process exit code: ``0`` when all skills are valid, ``1`` when
        any violation is found or the skills root is missing.
    """
    skills_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("skills")
    if not skills_root.is_dir():
        print(f"Skills directory not found: {skills_root}", file=sys.stderr)
        return 1
    violations = validate_skills_tree(skills_root=skills_root)
    for violation in violations:
        print(violation)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
