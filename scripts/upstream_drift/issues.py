"""Tracking-issue rendering and filing via the ``gh`` CLI.

Issues are keyed by their exact title: an open issue whose title
matches is updated in place instead of creating a duplicate.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - fixed gh argv list, no shell

from upstream_drift.drift_result import DriftResult
from upstream_drift.tracked_skill import TrackedSkill

MAX_ISSUE_DIFF_LINES = 300


def _issue_title(
    skill: TrackedSkill,
) -> str:
    """Build the deterministic tracking-issue title for a skill.

    The title is the idempotency key: an open issue with this exact
    title is updated instead of creating a duplicate.

    Args:
        skill: The drifted skill.

    Returns:
        The tracking-issue title.
    """
    return f"chore({skill.name}): upstream drift detected in {skill.repo}"


def _issue_body(
    result: DriftResult,
) -> str:
    """Build the tracking-issue body for a drift result.

    Args:
        result: A drift result with ``drifted=True``.

    Returns:
        Markdown issue body including a (possibly truncated) diff.
    """
    skill = result.skill
    diff_lines = result.diff.splitlines()
    truncated = len(diff_lines) > MAX_ISSUE_DIFF_LINES
    shown = "\n".join(diff_lines[:MAX_ISSUE_DIFF_LINES])
    truncation_note = (
        f"\n... diff truncated ({len(diff_lines)} lines total).\n" if truncated else ""
    )
    return (
        f"## Upstream drift: `skills/{skill.name}`\n\n"
        f"The upstream source of `skills/{skill.name}/SKILL.md` has diverged "
        f"from the local copy.\n\n"
        f"- Upstream: [`{skill.repo}/{skill.path}`]"
        f"(https://github.com/{skill.repo}/blob/main/{skill.path})\n"
        f"- Last synced upstream version: `{skill.version}`\n\n"
        f"Comparison ignores YAML frontmatter, line endings, and trailing "
        f"whitespace (see `scripts/check_upstream_drift.py`).\n\n"
        f"<details>\n<summary>Normalized diff (local vs upstream)</summary>\n\n"
        f"```diff\n{shown}\n```\n{truncation_note}\n</details>\n\n"
        f"Review the upstream changes and sync `skills/{skill.name}/SKILL.md` "
        f"(update `upstream.version` in its frontmatter after syncing).\n\n"
        f"*This issue is maintained automatically by the `upstream-drift` "
        f"workflow; it is updated in place on subsequent runs.*\n"
    )


def _run_gh(
    args: list[str],
    body: str | None = None,
) -> str:
    """Run a ``gh`` CLI command and return its stdout.

    Args:
        args: Arguments passed after the ``gh`` executable.
        body: Optional stdin payload (used with ``--body-file -``).

    Returns:
        The command's stdout as text.

    Raises:
        RuntimeError: If the command exits non-zero.
    """
    completed = subprocess.run(  # noqa: S603 # nosec B603 B607 - fixed gh argv
        ["gh", *args],
        input=body,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        msg = f"gh {' '.join(args)} failed: {completed.stderr.strip()}"
        raise RuntimeError(msg)
    return completed.stdout


def file_tracking_issue(
    result: DriftResult,
    github_repo: str,
) -> str:
    """Open or update the drift tracking issue for a skill.

    Searches open issues for an exact title match; updates the body of
    an existing issue in place, otherwise creates a new one.

    Args:
        result: A drift result with ``drifted=True``.
        github_repo: Repository slug (``owner/name``) to file the issue in.

    Returns:
        A short human-readable action summary (created/updated + URL).

    Raises:
        RuntimeError: If any ``gh`` invocation fails.
    """
    title = _issue_title(skill=result.skill)
    body = _issue_body(result=result)
    listing = _run_gh(
        args=[
            "issue",
            "list",
            "--repo",
            github_repo,
            "--state",
            "open",
            "--search",
            f"in:title {title}",
            "--json",
            "number,title",
        ],
    )
    issues = json.loads(listing) or []
    existing = [issue for issue in issues if issue.get("title") == title]
    if existing:
        number = str(existing[0]["number"])
        _run_gh(
            args=[
                "issue",
                "edit",
                number,
                "--repo",
                github_repo,
                "--body-file",
                "-",
            ],
            body=body,
        )
        return f"updated existing tracking issue #{number}"
    url = _run_gh(
        args=[
            "issue",
            "create",
            "--repo",
            github_repo,
            "--title",
            title,
            "--body-file",
            "-",
        ],
        body=body,
    ).strip()
    return f"created tracking issue {url}"
