"""Tests for the ``upstream_drift`` package and its CLI.

The library lives in ``scripts/upstream_drift/`` (importable because
``tests/conftest.py`` puts ``scripts/`` on ``sys.path``); the thin CLI
``scripts/check_upstream_drift.py`` is loaded from its file path.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from assertpy import assert_that
from upstream_drift import compare, discovery, fetch, issues
from upstream_drift.drift_result import DriftResult

REPO_ROOT = Path(__file__).resolve().parents[1]

UPSTREAM_SKILL = (
    "---\n"
    "name: example\n"
    "description: Example skill.\n"
    "upstream:\n"
    "  repo: anthropics/claude-code\n"
    "  path: plugins/frontend-design/skills/frontend-design/SKILL.md\n"
    '  version: "1.1.0"\n'
    "---\n"
    "\n"
    "# Body\n"
    "\n"
    "Shared content.\n"
)


def _load_cli_module() -> ModuleType:
    """Load the ``check_upstream_drift`` CLI from the scripts directory.

    Returns:
        The loaded module object.

    Raises:
        RuntimeError: If the module spec or loader cannot be constructed.
    """
    path = REPO_ROOT / "scripts" / "check_upstream_drift.py"
    spec = importlib.util.spec_from_file_location(
        name="check_upstream_drift",
        location=path,
    )
    if spec is None:
        msg = f"Could not load module spec from {path}"
        raise RuntimeError(msg)
    loader = spec.loader
    if loader is None:
        msg = f"Module spec for {path} has no loader"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _write_skill(
    tmp_path: Path,
    dir_name: str,
    content: str,
) -> Path:
    """Create ``skills/<dir_name>/SKILL.md`` with the given content.

    Args:
        tmp_path: Pytest temporary directory acting as fake repo root.
        dir_name: Skill directory name under ``skills/``.
        content: SKILL.md file content.

    Returns:
        Path to the created SKILL.md file.
    """
    skill_dir = tmp_path / "skills" / dir_name
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(content, encoding="utf-8")
    return skill_md


def test_normalize_body_strips_frontmatter_and_whitespace() -> None:
    """Frontmatter, CRLF endings, and trailing whitespace are normalized."""
    text = "---\r\nname: a\r\n---\r\n\r\n# Title  \r\nline\t\r\n\r\n\r\n"

    assert_that(compare.normalize_body(text=text)).is_equal_to("# Title\nline\n")


def test_normalize_body_without_frontmatter_keeps_content() -> None:
    """Documents without frontmatter are normalized whole."""
    assert_that(compare.normalize_body(text="# Title \n\n")).is_equal_to("# Title\n")


def test_normalize_body_blank_document_is_empty() -> None:
    """A blank document normalizes to the empty string."""
    assert_that(compare.normalize_body(text="---\nname: a\n---\n\n\n")).is_empty()


def test_frontmatter_only_differences_are_not_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local and upstream differing only in frontmatter are in sync."""
    skill_md = _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    skill = discovery.find_tracked_skills(skills_root=tmp_path / "skills")[0]
    upstream_text = (
        "---\nname: frontend-design\ndescription: Different metadata.\n---\n"
        "\n# Body\n\nShared content.\n"
    )
    monkeypatch.setattr(
        compare,
        "fetch_upstream_text",
        lambda repo, path, ref="main": upstream_text,
    )

    drift = compare.check_skill_drift(skill=skill)

    assert_that(skill.skill_md).is_equal_to(skill_md)
    assert_that(drift.drifted).is_false()
    assert_that(drift.diff).is_empty()


def test_body_differences_are_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed upstream body is reported as drift with a diff."""
    _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    skill = discovery.find_tracked_skills(skills_root=tmp_path / "skills")[0]
    monkeypatch.setattr(
        compare,
        "fetch_upstream_text",
        lambda repo, path, ref="main": "# Body\n\nRewritten upstream.\n",
    )

    drift = compare.check_skill_drift(skill=skill)

    assert_that(drift.drifted).is_true()
    assert_that(drift.diff).contains("+Rewritten upstream.")
    assert_that(drift.diff).contains("-Shared content.")


def test_find_tracked_skills_ignores_untracked(tmp_path: Path) -> None:
    """Skills without an upstream block are not tracked."""
    _write_skill(
        tmp_path=tmp_path,
        dir_name="plain",
        content="---\nname: plain\ndescription: No upstream.\n---\n",
    )
    _write_skill(
        tmp_path=tmp_path,
        dir_name="tracked",
        content=UPSTREAM_SKILL.replace("name: example", "name: tracked"),
    )

    tracked = discovery.find_tracked_skills(skills_root=tmp_path / "skills")

    assert_that([skill.name for skill in tracked]).is_equal_to(["tracked"])
    assert_that(tracked[0].repo).is_equal_to("anthropics/claude-code")
    assert_that(tracked[0].version).is_equal_to("1.1.0")


def test_find_tracked_skills_rejects_malformed_upstream(tmp_path: Path) -> None:
    """A malformed upstream block raises ValueError."""
    _write_skill(
        tmp_path=tmp_path,
        dir_name="broken",
        content=(
            "---\nname: broken\ndescription: Bad upstream.\n"
            "upstream:\n  repo: a/b\n---\n"
        ),
    )

    with pytest.raises(ValueError, match="upstream.path"):
        discovery.find_tracked_skills(skills_root=tmp_path / "skills")


def test_fetch_upstream_text_rejects_bad_repo() -> None:
    """Repo slugs that escape the raw.githubusercontent.com host fail."""
    with pytest.raises(RuntimeError):
        fetch.fetch_upstream_text(repo="../../evil.example.com", path="x")


def test_issue_title_is_deterministic(tmp_path: Path) -> None:
    """The tracking-issue title is stable across runs (idempotency key)."""
    _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    skill = discovery.find_tracked_skills(skills_root=tmp_path / "skills")[0]

    title = issues._issue_title(skill=skill)

    assert_that(title).is_equal_to(issues._issue_title(skill=skill))
    assert_that(title).is_equal_to(
        "chore(example): upstream drift detected in anthropics/claude-code"
    )


def test_issue_body_truncates_long_diffs(tmp_path: Path) -> None:
    """Diffs longer than the cap are truncated with a note."""
    _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    skill = discovery.find_tracked_skills(skills_root=tmp_path / "skills")[0]
    diff = "\n".join(f"+line {i}" for i in range(issues.MAX_ISSUE_DIFF_LINES + 50))
    result = DriftResult(skill=skill, drifted=True, diff=diff)

    body = issues._issue_body(result=result)

    assert_that(body).contains("diff truncated")
    assert_that(body).contains(f"+line {issues.MAX_ISSUE_DIFF_LINES - 1}")
    assert_that(body).does_not_contain(f"+line {issues.MAX_ISSUE_DIFF_LINES}")


def test_file_tracking_issue_updates_existing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An open issue with the exact title is edited, not duplicated."""
    _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    skill = discovery.find_tracked_skills(skills_root=tmp_path / "skills")[0]
    result = DriftResult(skill=skill, drifted=True, diff="+x\n-y\n")
    title = issues._issue_title(skill=skill)
    calls: list[list[str]] = []

    def fake_run_gh(args: list[str], body: str | None = None) -> str:
        """Record gh invocations and fake an exact-title list match."""
        calls.append(args)
        if args[:2] == ["issue", "list"]:
            return json.dumps([{"number": 42, "title": title}])
        return ""

    monkeypatch.setattr(issues, "_run_gh", fake_run_gh)

    action = issues.file_tracking_issue(result=result, github_repo="o/r")

    assert_that(action).is_equal_to("updated existing tracking issue #42")
    assert_that(calls[1][:3]).is_equal_to(["issue", "edit", "42"])


def test_file_tracking_issue_creates_when_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a matching open issue, a new one is created."""
    _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    skill = discovery.find_tracked_skills(skills_root=tmp_path / "skills")[0]
    result = DriftResult(skill=skill, drifted=True, diff="+x\n")
    calls: list[list[str]] = []

    def fake_run_gh(args: list[str], body: str | None = None) -> str:
        """Record gh invocations and fake a no-match issue list."""
        calls.append(args)
        if args[:2] == ["issue", "list"]:
            return json.dumps([{"number": 7, "title": "unrelated"}])
        return "https://github.com/o/r/issues/43\n"

    monkeypatch.setattr(issues, "_run_gh", fake_run_gh)

    action = issues.file_tracking_issue(result=result, github_repo="o/r")

    assert_that(action).is_equal_to(
        "created tracking issue https://github.com/o/r/issues/43"
    )
    assert_that(calls[1][:2]).is_equal_to(["issue", "create"])


def test_main_reports_drift_in_check_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check-only mode exits 1 and prints the diff on drift."""
    cli = _load_cli_module()
    _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    monkeypatch.setattr(
        compare,
        "fetch_upstream_text",
        lambda repo, path, ref="main": "# Other\n",
    )

    code = cli.main(argv=["--skills-root", str(tmp_path / "skills")])

    captured = capsys.readouterr()
    assert_that(code).is_equal_to(1)
    assert_that(captured.out).contains("example: DRIFT")
    assert_that(captured.out).contains("--- diff for example ---")


def test_main_passes_when_in_sync(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check-only mode exits 0 when local matches upstream."""
    cli = _load_cli_module()
    _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    monkeypatch.setattr(
        compare,
        "fetch_upstream_text",
        lambda repo, path, ref="main": "# Body\n\nShared content.\n",
    )

    code = cli.main(argv=["--skills-root", str(tmp_path / "skills")])

    captured = capsys.readouterr()
    assert_that(code).is_equal_to(0)
    assert_that(captured.out).contains("example: in sync")


def test_main_passes_with_no_tracked_skills(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With no upstream blocks anywhere, the check is a no-op success."""
    cli = _load_cli_module()
    _write_skill(
        tmp_path=tmp_path,
        dir_name="plain",
        content="---\nname: plain\ndescription: No upstream.\n---\n",
    )

    code = cli.main(argv=["--skills-root", str(tmp_path / "skills")])

    captured = capsys.readouterr()
    assert_that(code).is_equal_to(0)
    assert_that(captured.out).contains("No skills declare an 'upstream'")


def test_main_errors_on_missing_skills_root(tmp_path: Path) -> None:
    """A missing skills root is an operational error (exit 2)."""
    cli = _load_cli_module()

    code = cli.main(argv=["--skills-root", str(tmp_path / "nope")])

    assert_that(code).is_equal_to(2)
