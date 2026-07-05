"""Body normalization and drift comparison for tracked skills.

Comparison normalization (applied to both sides):

- the YAML frontmatter block is stripped, so intentionally divergent
  metadata (``name``, ``license``, the ``upstream`` block itself) never
  counts as drift — only the Markdown body is compared,
- Windows (CRLF) and legacy Mac (CR) line endings are normalized to
  Unix newlines,
- trailing whitespace is stripped from every line,
- leading and trailing blank lines around the body are removed.
"""

from __future__ import annotations

import difflib

from skill_frontmatter import split_frontmatter

from upstream_drift.drift_result import DriftResult
from upstream_drift.fetch import fetch_upstream_text
from upstream_drift.tracked_skill import TrackedSkill


def normalize_body(
    text: str,
) -> str:
    """Normalize a document for drift comparison.

    Strips YAML frontmatter, normalizes line endings to ``\\n``, strips
    trailing whitespace from every line, and drops leading and trailing
    blank lines.

    Args:
        text: Full document content.

    Returns:
        The normalized Markdown body, ending in a single newline (or
        empty when the body is blank).
    """
    _, body = split_frontmatter(text)
    lines = [line.rstrip() for line in body.split("\n")]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def check_skill_drift(
    skill: TrackedSkill,
) -> DriftResult:
    """Compare a tracked skill's body against its upstream source.

    Args:
        skill: The tracked skill to compare.

    Returns:
        The drift result, including a unified diff when drifted.
    """
    local_body = normalize_body(
        text=skill.skill_md.read_text(encoding="utf-8"),
    )
    upstream_body = normalize_body(
        text=fetch_upstream_text(repo=skill.repo, path=skill.path),
    )
    if local_body == upstream_body:
        return DriftResult(skill=skill, drifted=False, diff="")
    diff = "".join(
        difflib.unified_diff(
            local_body.splitlines(keepends=True),
            upstream_body.splitlines(keepends=True),
            fromfile=f"local: {skill.skill_md.as_posix()}",
            tofile=f"upstream: {skill.repo}/{skill.path}@main",
        ),
    )
    return DriftResult(skill=skill, drifted=True, diff=diff)
