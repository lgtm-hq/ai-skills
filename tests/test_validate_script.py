"""Tests for the repository validation script."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def repo_root() -> Path:
    """Return the absolute path to the repository root (parent of ``tests/``).

    Returns:
        Path: Root directory of the checkout under test.
    """
    return Path(__file__).resolve().parents[1]


def _copy_validate_script(
    repo_root: Path,
    tmp_path: Path,
) -> Path:
    """Copy the validation script into a temporary repository."""
    script_path = tmp_path / "scripts" / "validate.sh"
    script_path.parent.mkdir()
    shutil.copy2(repo_root / "scripts" / "validate.sh", script_path)
    return script_path


def _run_validate(
    script_path: Path,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    """Run the validation script in a temporary repository."""
    return subprocess.run(
        ["bash", str(script_path)],
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
    )


def test_validate_skips_when_skills_directory_is_missing(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    """Skip successfully when a repository has no skills directory yet."""
    script_path = _copy_validate_script(repo_root=repo_root, tmp_path=tmp_path)

    result = _run_validate(script_path=script_path, cwd=tmp_path)

    assert result.returncode == 0
    assert "No skills/ directory" in result.stdout


def test_validate_accepts_matching_skill_and_agents_entry(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    """Accept a skill when SKILL.md frontmatter and AGENTS.md agree."""
    script_path = _copy_validate_script(repo_root=repo_root, tmp_path=tmp_path)
    skill_dir = tmp_path / "skills" / "example"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: example\ndescription: Example skill.\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text(
        "- `example` - Example skill.\n", encoding="utf-8"
    )

    result = _run_validate(script_path=script_path, cwd=tmp_path)

    assert result.returncode == 0
    assert "Validation passed." in result.stdout


def test_validate_rejects_missing_agents_entry(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    """Reject a skill directory that is not listed in AGENTS.md."""
    script_path = _copy_validate_script(repo_root=repo_root, tmp_path=tmp_path)
    skill_dir = tmp_path / "skills" / "example"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: example\ndescription: Example skill.\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text("", encoding="utf-8")

    result = _run_validate(script_path=script_path, cwd=tmp_path)

    assert result.returncode == 1
    assert "AGENTS.md missing skill entry for: example" in result.stdout


def test_validate_accepts_agents_entry_with_regex_special_chars_in_skill_name(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    """Accept AGENTS lines when skill names include ripgrep metacharacters."""
    script_path = _copy_validate_script(repo_root=repo_root, tmp_path=tmp_path)
    skill_dir = tmp_path / "skills" / "alpha+beta"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: alpha+beta\ndescription: Example skill.\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text(
        "- `alpha+beta` - Example skill with plus in the id.\n",
        encoding="utf-8",
    )

    result = _run_validate(script_path=script_path, cwd=tmp_path)

    assert result.returncode == 0
    assert "Validation passed." in result.stdout


def test_validate_rejects_agents_entry_with_path_like_skill_name(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    """Reject AGENTS.md list items whose skill id looks like a path traversal."""
    script_path = _copy_validate_script(repo_root=repo_root, tmp_path=tmp_path)
    skill_dir = tmp_path / "skills" / "safe-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: safe-skill\ndescription: Legitimate skill.\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text(
        "- `safe-skill` - OK.\n- `../scripts` - Unsafe id.\n",
        encoding="utf-8",
    )

    result = _run_validate(script_path=script_path, cwd=tmp_path)

    assert result.returncode == 1
    assert "AGENTS.md contains invalid skill name: ../scripts" in result.stdout
