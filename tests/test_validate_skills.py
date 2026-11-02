"""Tests for ``scripts/validate_skills.py``."""

from __future__ import annotations

from pathlib import Path

import pytest
from assertpy import assert_that

import ai_skills_engine.validate_skills as mod

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_skill(
    tmp_path: Path,
    dir_name: str,
    content: str,
    newline: str = "\n",
) -> Path:
    """Create ``skills/<dir_name>/SKILL.md`` with the given content.

    Args:
        tmp_path: Pytest temporary directory acting as fake repo root.
        dir_name: Skill directory name under ``skills/``.
        content: SKILL.md file content (using ``\\n`` line endings).
        newline: Line ending to write; pass ``"\\r\\n"`` for CRLF files.

    Returns:
        Path to the created SKILL.md file.
    """
    skill_dir = tmp_path / "skills" / dir_name
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_bytes(content.replace("\n", newline).encode("utf-8"))
    return skill_md


def test_valid_skill_passes(tmp_path: Path) -> None:
    """A well-formed SKILL.md produces no violations."""
    skill_md = _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content="---\nname: example\ndescription: Example skill.\n---\n\n# Body\n",
    )

    violations = mod.validate_skill(skill_md=skill_md)

    assert_that(violations).is_empty()


def test_crlf_skill_passes(tmp_path: Path) -> None:
    """A CRLF SKILL.md is normalized before parsing and passes."""
    skill_md = _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content="---\nname: example\ndescription: Example skill.\n---\n\n# Body\n",
        newline="\r\n",
    )

    violations = mod.validate_skill(skill_md=skill_md)

    assert_that(violations).is_empty()


def test_one_char_description_passes(tmp_path: Path) -> None:
    """A one-character description is non-empty and therefore valid."""
    skill_md = _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content="---\nname: example\ndescription: x\n---\n",
    )

    violations = mod.validate_skill(skill_md=skill_md)

    assert_that(violations).is_empty()


def test_max_length_description_passes(tmp_path: Path) -> None:
    """A description of exactly 1024 characters is accepted."""
    description = "x" * 1024
    skill_md = _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=f"---\nname: example\ndescription: {description}\n---\n",
    )

    violations = mod.validate_skill(skill_md=skill_md)

    assert_that(violations).is_empty()


@pytest.mark.parametrize(
    ("content", "expected_fragment"),
    [
        pytest.param(
            "---\nname: example\ndescription:\n  - one\n  - two\n---\n",
            "'description' must be a string, got list",
            id="list-valued-description",
        ),
        pytest.param(
            "---\nname: example\ndescription:\n  key: value\n---\n",
            "'description' must be a string, got dict",
            id="mapping-valued-description",
        ),
        pytest.param(
            "---\nname: example\ndescription: ''\n---\n",
            "'description' must be a non-empty string",
            id="empty-description",
        ),
        pytest.param(
            "---\nname: example\ndescription: '   '\n---\n",
            "'description' must be a non-empty string",
            id="whitespace-only-description",
        ),
        pytest.param(
            "---\nname: example\n---\n",
            "missing 'description' in frontmatter",
            id="missing-description",
        ),
        pytest.param(
            "---\ndescription: Example skill.\n---\n",
            "missing 'name' in frontmatter",
            id="missing-name",
        ),
        pytest.param(
            "---\nname: 123\ndescription: Example skill.\n---\n",
            "'name' must be a string, got int",
            id="non-string-name",
        ),
        pytest.param(
            "---\n- just\n- a\n- list\n---\n",
            "frontmatter must be a YAML mapping, got list",
            id="list-frontmatter",
        ),
        pytest.param(
            "---\nname: [unclosed\ndescription: Example skill.\n---\n",
            "frontmatter is not valid YAML",
            id="unparseable-yaml",
        ),
        pytest.param(
            "---\nname: example\ndescription: Never closed.\n",
            "missing opening/closing --- frontmatter delimiters",
            id="missing-closing-delimiter",
        ),
        pytest.param(
            "name: example\ndescription: No frontmatter fences.\n",
            "missing opening/closing --- frontmatter delimiters",
            id="missing-opening-delimiter",
        ),
    ],
)
def test_invalid_frontmatter_is_rejected(
    tmp_path: Path,
    content: str,
    expected_fragment: str,
) -> None:
    """Each malformed-frontmatter variant yields a violation naming the file."""
    skill_md = _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=content,
    )

    violations = mod.validate_skill(skill_md=skill_md)

    assert_that(violations).is_not_empty()
    assert_that(any(expected_fragment in v for v in violations)).is_true()
    assert_that(all(str(skill_md) in v for v in violations)).is_true()


def test_overlong_description_is_rejected(tmp_path: Path) -> None:
    """A description over 1024 characters is rejected."""
    description = "x" * 1025
    skill_md = _write_skill(
        tmp_path=tmp_path,
        dir_name="example",
        content=f"---\nname: example\ndescription: {description}\n---\n",
    )

    violations = mod.validate_skill(skill_md=skill_md)

    assert_that(violations).is_equal_to(
        [
            (
                f"{skill_md}: 'description' is 1025 characters, "
                "exceeds the 1024-character limit"
            ),
        ]
    )


def test_name_directory_mismatch_is_rejected(tmp_path: Path) -> None:
    """A ``name`` that differs from the directory basename is rejected."""
    skill_md = _write_skill(
        tmp_path=tmp_path,
        dir_name="foo",
        content="---\nname: bar\ndescription: Example skill.\n---\n",
    )

    violations = mod.validate_skill(skill_md=skill_md)

    assert_that(violations).is_equal_to(
        [
            f"{skill_md}: 'name' 'bar' does not match directory name 'foo'",
        ]
    )


def test_validate_skills_tree_collects_all_violations(tmp_path: Path) -> None:
    """The tree walker aggregates violations across skill directories."""
    _write_skill(
        tmp_path=tmp_path,
        dir_name="good",
        content="---\nname: good\ndescription: Fine skill.\n---\n",
    )
    _write_skill(
        tmp_path=tmp_path,
        dir_name="bad",
        content="---\nname: mismatch\ndescription:\n  - junk\n---\n",
    )

    violations = mod.validate_skills_tree(skills_root=tmp_path / "skills")

    assert_that(violations).is_length(2)
    assert_that(
        any("'description' must be a string" in v for v in violations)
    ).is_true()
    assert_that(any("does not match directory name" in v for v in violations)).is_true()


def test_validate_skills_tree_passes_on_real_repo() -> None:
    """The real skills tree in this repository must validate cleanly."""

    violations = mod.validate_skills_tree(skills_root=REPO_ROOT / "skills")

    assert_that(violations).is_empty()
