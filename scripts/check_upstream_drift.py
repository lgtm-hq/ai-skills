#!/usr/bin/env python3
"""Check upstream-sourced skills for content drift.

Thin CLI over the ``upstream_drift`` package. Scans ``skills/*/SKILL.md``
for frontmatter declaring an ``upstream`` block::

    upstream:
      repo: anthropics/claude-code
      path: plugins/frontend-design/skills/frontend-design/SKILL.md
      version: "1.1.0"

For each such skill the referenced file is fetched from the upstream
repository's default branch (via ``raw.githubusercontent.com``) and its
normalized Markdown body is compared against the local skill's body
(see ``upstream_drift.compare`` for the normalization rules).

Modes:

- default (check-only): print a drift report; exit ``1`` when any
  tracked skill has drifted, ``0`` otherwise.
- ``--file-issue``: additionally open (or update, keyed by exact issue
  title) a tracking issue via the ``gh`` CLI; exit ``0`` when drift was
  reported successfully, since the drift is then tracked.

Exit codes: ``0`` no drift (or drift filed as an issue), ``1`` drift in
check-only mode, ``2`` operational error (fetch failure, ``gh`` failure,
malformed ``upstream`` block).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from upstream_drift import (
    DriftResult,
    check_skill_drift,
    file_tracking_issue,
    find_tracked_skills,
)


def _parse_args(
    argv: list[str],
) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list (excluding the program name).

    Returns:
        The parsed namespace with ``skills_root``, ``file_issue``, and
        ``github_repo`` attributes.
    """
    parser = argparse.ArgumentParser(
        description="Check upstream-sourced skills for content drift.",
    )
    parser.add_argument(
        "--skills-root",
        type=Path,
        default=Path("skills"),
        help="Path to the skills/ directory (default: skills).",
    )
    parser.add_argument(
        "--file-issue",
        action="store_true",
        help="Open or update a tracking issue per drifted skill (needs gh).",
    )
    parser.add_argument(
        "--github-repo",
        default="lgtm-hq/ai-skills",
        help="Repository slug to file tracking issues in.",
    )
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
) -> int:
    """Check all tracked skills for upstream drift.

    Args:
        argv: Optional argument list for testing; defaults to
            ``sys.argv[1:]``.

    Returns:
        Process exit code: ``0`` when no skill drifted (or drift was
        filed as tracking issues), ``1`` when drift was found in
        check-only mode, ``2`` on operational errors.
    """
    args = _parse_args(argv=sys.argv[1:] if argv is None else argv)
    if not args.skills_root.is_dir():
        print(f"Skills directory not found: {args.skills_root}", file=sys.stderr)
        return 2
    try:
        tracked = find_tracked_skills(skills_root=args.skills_root)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not tracked:
        print("No skills declare an 'upstream' frontmatter block.")
        return 0
    drifted: list[DriftResult] = []
    for skill in tracked:
        try:
            result = check_skill_drift(skill=skill)
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 2
        status = "DRIFT" if result.drifted else "in sync"
        print(f"{skill.name}: {status} ({skill.repo}/{skill.path})")
        if result.drifted:
            drifted.append(result)
    if not drifted:
        return 0
    if not args.file_issue:
        for result in drifted:
            print(f"\n--- diff for {result.skill.name} ---\n{result.diff}")
        return 1
    for result in drifted:
        try:
            action = file_tracking_issue(
                result=result,
                github_repo=args.github_repo,
            )
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 2
        print(f"{result.skill.name}: {action}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
