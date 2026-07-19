"""Tests for the repository validation script."""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 - tests only; run copied validate.sh via argv list without shell
from pathlib import Path

from assertpy import assert_that
from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]


def _copy_validate_script(
    repo_root: Path,
    tmp_path: Path,
) -> Path:
    """Copy ``validate.sh`` and its Python helpers into an isolated temp tree.

    Args:
        repo_root: Path to the real repository root (source of ``validate.sh``).
        tmp_path: Pytest temporary directory acting as fake repo root.

    Returns:
        Path to the copied ``validate.sh`` under ``tmp_path``.
    """
    script_path = tmp_path / "scripts" / "validate.sh"
    script_path.parent.mkdir(parents=True, exist_ok=False)
    shutil.copy2(src=repo_root / "scripts" / "validate.sh", dst=script_path)
    for helper in (
        "bake_vendor_indexes.py",
        "validate_skills.py",
        "skill_frontmatter.py",
        "check_suppressions.py",
        "check_bare_asserts.py",
    ):
        shutil.copy2(
            src=repo_root / "scripts" / helper,
            dst=script_path.parent / helper,
        )
    shutil.copytree(
        src=repo_root / "scripts" / "vendor_registry",
        dst=script_path.parent / "vendor_registry",
    )
    shutil.copy2(src=repo_root / "vendors.yaml", dst=tmp_path / "vendors.yaml")
    shutil.copy2(src=repo_root / "NOTICE.md", dst=tmp_path / "NOTICE.md")
    shutil.copytree(
        src=repo_root / "vendor-indexes",
        dst=tmp_path / "vendor-indexes",
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
    return subprocess.run(  # noqa: S603 # nosec B603 B607 - fixed bash argv, no shell
        ["bash", str(script_path)],  # noqa: S607 - bash resolved from PATH deliberately
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

    assert_that(result.returncode).is_equal_to(0)
    assert_that(result.stdout).contains("No skills/ directory")
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

    assert_that(result.returncode).is_equal_to(0)
    assert_that(result.stdout).contains("Validation passed.")
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

    assert_that(result.returncode).is_equal_to(1)
    assert_that(result.stdout).contains("AGENTS.md missing skill entry for: example")
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

    assert_that(result.returncode).is_equal_to(0)
    assert_that(result.stdout).contains("Validation passed.")
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

    assert_that(result.returncode).is_equal_to(1)
    assert_that(result.stdout).contains("does not match directory name 'foo'")
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

    assert_that(result.returncode).is_equal_to(1)
    assert_that(result.stdout).contains("'description' must be a string, got list")
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

    assert_that(result.returncode).is_equal_to(0)
    assert_that(result.stdout).contains("Validation passed.")
    logger.info("[TEST] CRLF skill file accepted: rc={}", result.returncode)


def test_validate_frontmatter_uses_cwd_skills_not_script_location(
    tmp_path: Path,
) -> None:
    """Frontmatter checks must use cwd ``skills/``, not the script tree."""
    repo_copy = tmp_path / "repo"
    other_cwd = tmp_path / "other"
    script_path = _copy_validate_script(repo_root=REPO_ROOT, tmp_path=repo_copy)

    good_skill = repo_copy / "skills" / "example"
    good_skill.mkdir(parents=True)
    (good_skill / "SKILL.md").write_text(
        "---\nname: example\ndescription: Valid skill.\n---\n",
        encoding="utf-8",
    )
    (repo_copy / "AGENTS.md").write_text(
        "- `example` - Valid skill.\n", encoding="utf-8"
    )

    bad_skill = other_cwd / "skills" / "example"
    bad_skill.mkdir(parents=True)
    (bad_skill / "SKILL.md").write_text(
        "---\nname: example\ndescription:\n  - not\n  - a\n  - string\n---\n",
        encoding="utf-8",
    )
    (other_cwd / "AGENTS.md").write_text(
        "- `example` - Listed but invalid frontmatter.\n", encoding="utf-8"
    )

    result = _run_validate(script_path=script_path, cwd=other_cwd)

    assert_that(result.returncode).is_equal_to(1)
    assert_that(result.stdout).contains("'description' must be a string, got list")
    logger.info("[TEST] cwd skills tree used for frontmatter: rc={}", result.returncode)


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

    assert_that(result.returncode).is_equal_to(1)
    assert_that(result.stdout).contains(
        "AGENTS.md contains invalid skill name: ../scripts"
    )
    logger.info("[TEST] path-like skill name rejected: rc={}", result.returncode)
