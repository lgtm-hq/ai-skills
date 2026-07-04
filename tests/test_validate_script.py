"""Tests for the repository validation script."""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 - tests only; run copied validate.sh via argv list without shell
from pathlib import Path

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]


def _copy_validate_script(
    repo_root: Path,
    tmp_path: Path,
) -> Path:
    """Copy ``validate.sh`` and its Python helper into an isolated temp tree.

    Args:
        repo_root: Path to the real repository root (source of ``validate.sh``).
        tmp_path: Pytest temporary directory acting as fake repo root.

    Returns:
        Path to the copied ``validate.sh`` under ``tmp_path``.
    """
    script_path = tmp_path / "scripts" / "validate.sh"
    script_path.parent.mkdir(parents=True, exist_ok=False)
    shutil.copy2(src=repo_root / "scripts" / "validate.sh", dst=script_path)
    shutil.copy2(
        src=repo_root / "scripts" / "validate_skills.py",
        dst=script_path.parent / "validate_skills.py",
    )
    logger.debug("Copied validate.sh to {}", script_path)
    return script_path


def _run_validate(
    script_path: Path,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    """Run the validation script in a temporary repository.

    Args:
        script_path: Path to ``validate.sh`` to execute.
        cwd: Working directory passed to the subprocess (fake repo root).

    Returns:
        The ``subprocess.CompletedProcess`` from invoking bash with captured
        ``stdout`` and ``stderr`` (``text=True``).
    """
    logger.debug("Running validate.sh cwd={} script={}", cwd, script_path)
    env = dict(os.environ)
    # The fake repo root has no pyproject.toml; point `uv run` at the real
    # project so the frontmatter validator resolves its dependencies.
    env["UV_PROJECT"] = str(REPO_ROOT)
    return subprocess.run(  # nosec B603 B607 - argv is fixed [bash, script_path]; test fixtures supply path, shell=False implicit
        ["bash", str(script_path)],
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )


def test_validate_skips_when_skills_directory_is_missing(
    tmp_path: Path,
) -> None:
    """Skip successfully when a repository has no skills directory yet."""
    script_path = _copy_validate_script(repo_root=REPO_ROOT, tmp_path=tmp_path)

    result = _run_validate(script_path=script_path, cwd=tmp_path)

    assert result.returncode == 0
    assert "No skills/ directory" in result.stdout
    logger.info(
        "[TEST] skills dir missing: rc={} (expect skip message in stdout)",
        result.returncode,
    )


def test_validate_accepts_matching_skill_and_agents_entry(
    tmp_path: Path,
) -> None:
    """Accept a skill when SKILL.md frontmatter and AGENTS.md agree."""
    script_path = _copy_validate_script(repo_root=REPO_ROOT, tmp_path=tmp_path)
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
    logger.info("[TEST] matching skill + AGENTS: rc={}", result.returncode)


def test_validate_rejects_missing_agents_entry(
    tmp_path: Path,
) -> None:
    """Reject a skill directory that is not listed in AGENTS.md."""
    script_path = _copy_validate_script(repo_root=REPO_ROOT, tmp_path=tmp_path)
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
    logger.info("[TEST] missing AGENTS entry: rc={}", result.returncode)


def test_validate_accepts_agents_entry_with_regex_special_chars_in_skill_name(
    tmp_path: Path,
) -> None:
    """Accept AGENTS lines when skill names include ripgrep metacharacters."""
    script_path = _copy_validate_script(repo_root=REPO_ROOT, tmp_path=tmp_path)
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
    logger.info("[TEST] regex-special chars in skill id: rc={}", result.returncode)


def test_validate_rejects_name_directory_mismatch(
    tmp_path: Path,
) -> None:
    """Reject a skill whose frontmatter name differs from its directory."""
    script_path = _copy_validate_script(repo_root=REPO_ROOT, tmp_path=tmp_path)
    skill_dir = tmp_path / "skills" / "foo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: bar\ndescription: Example skill.\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text("- `foo` - Example skill.\n", encoding="utf-8")

    result = _run_validate(script_path=script_path, cwd=tmp_path)

    assert result.returncode == 1
    assert "does not match directory name 'foo'" in result.stdout
    logger.info("[TEST] name/dir mismatch rejected: rc={}", result.returncode)


def test_validate_rejects_list_valued_description(
    tmp_path: Path,
) -> None:
    """Reject a skill whose description is a YAML list instead of a string."""
    script_path = _copy_validate_script(repo_root=REPO_ROOT, tmp_path=tmp_path)
    skill_dir = tmp_path / "skills" / "example"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: example\ndescription:\n  - one\n  - two\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text(
        "- `example` - Example skill.\n", encoding="utf-8"
    )

    result = _run_validate(script_path=script_path, cwd=tmp_path)

    assert result.returncode == 1
    assert "'description' must be a string, got list" in result.stdout
    logger.info("[TEST] list-valued description rejected: rc={}", result.returncode)


def test_validate_accepts_crlf_skill_file(
    tmp_path: Path,
) -> None:
    """Accept a SKILL.md that uses CRLF line endings."""
    script_path = _copy_validate_script(repo_root=REPO_ROOT, tmp_path=tmp_path)
    skill_dir = tmp_path / "skills" / "example"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(
        b"---\r\nname: example\r\ndescription: Example skill.\r\n---\r\n",
    )
    (tmp_path / "AGENTS.md").write_text(
        "- `example` - Example skill.\n", encoding="utf-8"
    )

    result = _run_validate(script_path=script_path, cwd=tmp_path)

    assert result.returncode == 0
    assert "Validation passed." in result.stdout
    logger.info("[TEST] CRLF skill file accepted: rc={}", result.returncode)


def test_validate_rejects_agents_entry_with_path_like_skill_name(
    tmp_path: Path,
) -> None:
    """Reject AGENTS.md list items whose skill id looks like a path traversal."""
    script_path = _copy_validate_script(repo_root=REPO_ROOT, tmp_path=tmp_path)
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
    logger.info("[TEST] path-like skill name rejected: rc={}", result.returncode)
