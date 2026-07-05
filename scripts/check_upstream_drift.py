#!/usr/bin/env python3
"""Check upstream-sourced skills for content drift.

Scans ``skills/*/SKILL.md`` for frontmatter declaring an ``upstream``
block::

    upstream:
      repo: anthropics/claude-code
      path: plugins/frontend-design/skills/frontend-design/SKILL.md
      version: "1.1.0"

For each such skill the referenced file is fetched from the upstream
repository's default branch (via ``raw.githubusercontent.com``) and its
Markdown body is compared against the local skill's body.

Comparison normalization (applied to both sides):

- the YAML frontmatter block is stripped, so intentionally divergent
  metadata (``name``, ``license``, the ``upstream`` block itself) never
  counts as drift — only the Markdown body is compared,
- Windows (CRLF) and legacy Mac (CR) line endings are normalized to
  Unix newlines,
- trailing whitespace is stripped from every line,
- leading and trailing blank lines around the body are removed.

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
import difflib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

FETCH_TIMEOUT_SECONDS = 30
MAX_ISSUE_DIFF_LINES = 300
RAW_URL_TEMPLATE = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"


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


@dataclass(frozen=True)
class DriftResult:
    """Outcome of comparing one tracked skill against upstream.

    Attributes:
        skill: The tracked skill that was compared.
        drifted: Whether the normalized bodies differ.
        diff: Unified diff of the normalized bodies (empty when equal).
    """

    skill: TrackedSkill
    drifted: bool
    diff: str


def _strip_frontmatter(
    text: str,
) -> str:
    """Return the Markdown body of a document, without YAML frontmatter.

    Line endings are normalized to Unix newlines first so the ``---``
    delimiters are detected reliably. Documents without a complete
    frontmatter block are returned whole (normalized).

    Args:
        text: Full document content.

    Returns:
        The content after the closing ``---`` delimiter, or the whole
        (newline-normalized) document when no frontmatter is present.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        return normalized
    end = normalized.find("\n---\n", 4)
    if end == -1:
        return normalized
    return normalized[end + len("\n---\n") :]


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
    body = _strip_frontmatter(text=text)
    lines = [line.rstrip() for line in body.split("\n")]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


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
        text = skill_md.read_text(encoding="utf-8")
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.startswith("---\n"):
            continue
        end = normalized.find("\n---\n", 4)
        if end == -1:
            continue
        frontmatter = yaml.safe_load(normalized[4:end])
        if not isinstance(frontmatter, dict) or "upstream" not in frontmatter:
            continue
        upstream = frontmatter["upstream"]
        if not isinstance(upstream, dict):
            msg = f"{skill_md}: 'upstream' must be a mapping"
            raise ValueError(msg)
        fields: dict[str, str] = {}
        for field in ("repo", "path", "version"):
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


def fetch_upstream_text(
    repo: str,
    path: str,
    ref: str = "main",
) -> str:
    """Fetch a file's raw content from a GitHub repository.

    Args:
        repo: Repository slug (``owner/name``).
        path: File path inside the repository.
        ref: Git ref to fetch from; defaults to ``main``.

    Returns:
        The file content decoded as UTF-8.

    Raises:
        RuntimeError: If the repo slug or path is unsafe, the fetch
            fails, or a non-200 status is returned.
    """
    if not re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", repo) or ".." in repo:
        msg = f"Refusing to fetch from suspicious repo slug: {repo!r}"
        raise RuntimeError(msg)
    if path.startswith("/") or ".." in path.split("/"):
        msg = f"Refusing to fetch suspicious upstream path: {path!r}"
        raise RuntimeError(msg)
    url = RAW_URL_TEMPLATE.format(repo=repo, ref=ref, path=path)
    try:
        with urllib.request.urlopen(  # noqa: S310 -- scheme/host pinned above
            url,
            timeout=FETCH_TIMEOUT_SECONDS,
        ) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        msg = f"Failed to fetch {url}: {exc}"
        raise RuntimeError(msg) from exc


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
    completed = subprocess.run(  # noqa: S603 -- fixed executable, no shell
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
