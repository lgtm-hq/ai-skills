"""Tests for ``scripts/generate_agents_md.py``."""

from __future__ import annotations

from pathlib import Path

from assertpy import assert_that

import ai_skills_engine.generate.agents_md as mod


def test_read_skill_meta_accepts_crlf_skill_file(tmp_path: Path) -> None:
    """``_read_skill_meta`` must parse YAML delimiters when the file uses CRLF."""

    skill_md = tmp_path / "SKILL.md"
    crlf_body = (
        "---\r\nname: example\r\ndescription: Example skill.\r\n---\r\n\r\n# Body\r\n"
    )
    skill_md.write_bytes(crlf_body.encode("utf-8"))

    skill_id, description = mod._read_skill_meta(skill_md=skill_md)

    assert_that(skill_id).is_equal_to("example")
    assert_that(description).is_equal_to("Example skill.")


def test_read_skill_meta_accepts_eof_closing_delimiter(tmp_path: Path) -> None:
    """Closing ``---`` at EOF without a trailing newline is valid."""

    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\nname: eofskill\ndescription: Ends at closing fence.\n---",
        encoding="utf-8",
    )

    skill_id, description = mod._read_skill_meta(skill_md=skill_md)

    assert_that(skill_id).is_equal_to("eofskill")
    assert_that(description).is_equal_to("Ends at closing fence.")
