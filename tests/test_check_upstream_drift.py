"""Tests for ``scripts/check_upstream_drift.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

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


def _load_module() -> ModuleType:
    """Load ``check_upstream_drift`` from the scripts directory.

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
    # Register before exec so dataclass annotation resolution
    # (PEP 563 strings) can find the module in sys.modules.
    sys.modules[spec.name] = module
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
    mod = _load_module()
    text = "---\r\nname: a\r\n---\r\n\r\n# Title  \r\nline\t\r\n\r\n\r\n"

    assert mod.normalize_body(text=text) == "# Title\nline\n"


def test_normalize_body_without_frontmatter_keeps_content() -> None:
    """Documents without frontmatter are normalized whole."""
    mod = _load_module()

    assert mod.normalize_body(text="# Title \n\n") == "# Title\n"


def test_normalize_body_blank_document_is_empty() -> None:
    """A blank document normalizes to the empty string."""
    mod = _load_module()

    assert mod.normalize_body(text="---\nname: a\n---\n\n\n") == ""


def test_frontmatter_only_differences_are_not_drift(tmp_path: Path) -> None:
    """Local and upstream differing only in frontmatter are in sync."""
    mod = _load_module()
    skill_md = _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    skill = mod.find_tracked_skills(skills_root=tmp_path / "skills")[0]
    upstream_text = (
        "---\nname: frontend-design\ndescription: Different metadata.\n---\n"
        "\n# Body\n\nShared content.\n"
    )

    original = mod.fetch_upstream_text
    mod.fetch_upstream_text = lambda repo, path, ref="main": upstream_text
    try:
        drift = mod.check_skill_drift(skill=skill)
    finally:
        mod.fetch_upstream_text = original

    assert skill.skill_md == skill_md
    assert drift.drifted is False
    assert drift.diff == ""


def test_body_differences_are_drift(tmp_path: Path) -> None:
    """A changed upstream body is reported as drift with a diff."""
    mod = _load_module()
    _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    skill = mod.find_tracked_skills(skills_root=tmp_path / "skills")[0]
    original = mod.fetch_upstream_text
    mod.fetch_upstream_text = (
        lambda repo, path, ref="main": "# Body\n\nRewritten upstream.\n"
    )
    try:
        drift = mod.check_skill_drift(skill=skill)
    finally:
        mod.fetch_upstream_text = original

    assert drift.drifted is True
    assert "+Rewritten upstream." in drift.diff
    assert "-Shared content." in drift.diff


def test_find_tracked_skills_ignores_untracked(tmp_path: Path) -> None:
    """Skills without an upstream block are not tracked."""
    mod = _load_module()
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

    tracked = mod.find_tracked_skills(skills_root=tmp_path / "skills")

    assert [skill.name for skill in tracked] == ["tracked"]
    assert tracked[0].repo == "anthropics/claude-code"
    assert tracked[0].version == "1.1.0"


def test_find_tracked_skills_rejects_malformed_upstream(tmp_path: Path) -> None:
    """A malformed upstream block raises ValueError."""
    mod = _load_module()
    _write_skill(
        tmp_path=tmp_path,
        dir_name="broken",
        content=(
            "---\nname: broken\ndescription: Bad upstream.\n"
            "upstream:\n  repo: a/b\n---\n"
        ),
    )

    with pytest.raises(ValueError, match="upstream.path"):
        mod.find_tracked_skills(skills_root=tmp_path / "skills")


def test_fetch_upstream_text_rejects_bad_repo() -> None:
    """Repo slugs that escape the raw.githubusercontent.com host fail."""
    mod = _load_module()

    with pytest.raises(RuntimeError):
        mod.fetch_upstream_text(repo="../../evil.example.com", path="x")


def test_issue_title_is_deterministic(tmp_path: Path) -> None:
    """The tracking-issue title is stable across runs (idempotency key)."""
    mod = _load_module()
    _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    skill = mod.find_tracked_skills(skills_root=tmp_path / "skills")[0]

    title = mod._issue_title(skill=skill)

    assert title == mod._issue_title(skill=skill)
    assert title == "chore(example): upstream drift detected in anthropics/claude-code"


def test_issue_body_truncates_long_diffs(tmp_path: Path) -> None:
    """Diffs longer than the cap are truncated with a note."""
    mod = _load_module()
    _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    skill = mod.find_tracked_skills(skills_root=tmp_path / "skills")[0]
    diff = "\n".join(f"+line {i}" for i in range(mod.MAX_ISSUE_DIFF_LINES + 50))
    result = mod.DriftResult(skill=skill, drifted=True, diff=diff)

    body = mod._issue_body(result=result)

    assert "diff truncated" in body
    assert f"+line {mod.MAX_ISSUE_DIFF_LINES - 1}" in body
    assert f"+line {mod.MAX_ISSUE_DIFF_LINES}" not in body


def test_file_tracking_issue_updates_existing(tmp_path: Path) -> None:
    """An open issue with the exact title is edited, not duplicated."""
    mod = _load_module()
    _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    skill = mod.find_tracked_skills(skills_root=tmp_path / "skills")[0]
    result = mod.DriftResult(skill=skill, drifted=True, diff="+x\n-y\n")
    title = mod._issue_title(skill=skill)
    calls: list[list[str]] = []

    def fake_run_gh(args: list[str], body: str | None = None) -> str:
        calls.append(args)
        if args[:2] == ["issue", "list"]:
            return json.dumps([{"number": 42, "title": title}])
        return ""

    original = mod._run_gh
    mod._run_gh = fake_run_gh
    try:
        action = mod.file_tracking_issue(result=result, github_repo="o/r")
    finally:
        mod._run_gh = original

    assert action == "updated existing tracking issue #42"
    assert calls[1][:3] == ["issue", "edit", "42"]


def test_file_tracking_issue_creates_when_absent(tmp_path: Path) -> None:
    """Without a matching open issue, a new one is created."""
    mod = _load_module()
    _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    skill = mod.find_tracked_skills(skills_root=tmp_path / "skills")[0]
    result = mod.DriftResult(skill=skill, drifted=True, diff="+x\n")
    calls: list[list[str]] = []

    def fake_run_gh(args: list[str], body: str | None = None) -> str:
        calls.append(args)
        if args[:2] == ["issue", "list"]:
            return json.dumps([{"number": 7, "title": "unrelated"}])
        return "https://github.com/o/r/issues/43\n"

    original = mod._run_gh
    mod._run_gh = fake_run_gh
    try:
        action = mod.file_tracking_issue(result=result, github_repo="o/r")
    finally:
        mod._run_gh = original

    assert action == "created tracking issue https://github.com/o/r/issues/43"
    assert calls[1][:2] == ["issue", "create"]


def test_main_reports_drift_in_check_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Check-only mode exits 1 and prints the diff on drift."""
    mod = _load_module()
    _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    original = mod.fetch_upstream_text
    mod.fetch_upstream_text = lambda repo, path, ref="main": "# Other\n"
    try:
        code = mod.main(argv=["--skills-root", str(tmp_path / "skills")])
    finally:
        mod.fetch_upstream_text = original

    captured = capsys.readouterr()
    assert code == 1
    assert "example: DRIFT" in captured.out
    assert "--- diff for example ---" in captured.out


def test_main_passes_when_in_sync(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Check-only mode exits 0 when local matches upstream."""
    mod = _load_module()
    _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=UPSTREAM_SKILL,
    )
    original = mod.fetch_upstream_text
    mod.fetch_upstream_text = (
        lambda repo, path, ref="main": "# Body\n\nShared content.\n"
    )
    try:
        code = mod.main(argv=["--skills-root", str(tmp_path / "skills")])
    finally:
        mod.fetch_upstream_text = original

    captured = capsys.readouterr()
    assert code == 0
    assert "example: in sync" in captured.out


def test_main_passes_with_no_tracked_skills(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With no upstream blocks anywhere, the check is a no-op success."""
    mod = _load_module()
    _write_skill(
        tmp_path=tmp_path,
        dir_name="plain",
        content="---\nname: plain\ndescription: No upstream.\n---\n",
    )

    code = mod.main(argv=["--skills-root", str(tmp_path / "skills")])

    captured = capsys.readouterr()
    assert code == 0
    assert "No skills declare an 'upstream'" in captured.out


def test_main_errors_on_missing_skills_root(tmp_path: Path) -> None:
    """A missing skills root is an operational error (exit 2)."""
    mod = _load_module()

    code = mod.main(argv=["--skills-root", str(tmp_path / "nope")])

    assert code == 2
