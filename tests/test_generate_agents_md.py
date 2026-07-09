"""Tests for ``scripts/generate_agents_md.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from assertpy import assert_that


def _load_generate_agents_md_module() -> ModuleType:
    """Load ``generate_agents_md`` from the scripts directory (not a package).

    Returns:
        The loaded module object.

    Raises:
        RuntimeError: If the module spec or loader cannot be constructed.
    """
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "generate_agents_md.py"
    spec = importlib.util.spec_from_file_location(
        name="generate_agents_md",
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


def test_read_skill_meta_accepts_crlf_skill_file(tmp_path: Path) -> None:
    """``_read_skill_meta`` must parse YAML delimiters when the file uses CRLF."""

    mod = _load_generate_agents_md_module()
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

    mod = _load_generate_agents_md_module()
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\nname: eofskill\ndescription: Ends at closing fence.\n---",
        encoding="utf-8",
    )

    skill_id, description = mod._read_skill_meta(skill_md=skill_md)

    assert_that(skill_id).is_equal_to("eofskill")
    assert_that(description).is_equal_to("Ends at closing fence.")
