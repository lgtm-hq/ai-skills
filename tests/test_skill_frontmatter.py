"""Tests for ``scripts/skill_frontmatter.py``."""

from __future__ import annotations

import pytest
from skill_frontmatter import split_frontmatter


@pytest.mark.parametrize(
    ("text", "expected_frontmatter", "expected_body"),
    [
        pytest.param(
            "---\nname: a\n---\n\n# Body\n",
            "name: a",
            "\n# Body\n",
            id="complete-block",
        ),
        pytest.param(
            "---\r\nname: a\r\n---\r\nbody\r\n",
            "name: a",
            "body\n",
            id="crlf-normalized",
        ),
        pytest.param(
            "---\rname: a\r---\rbody\r",
            "name: a",
            "body\n",
            id="cr-normalized",
        ),
        pytest.param(
            "---\nname: a\n---",
            "name: a",
            "",
            id="closing-fence-at-eof",
        ),
        pytest.param(
            "---\nname: a\n---  \n",
            "name: a",
            "",
            id="closing-fence-trailing-whitespace-only",
        ),
    ],
)
def test_split_frontmatter_extracts_block(
    text: str,
    expected_frontmatter: str,
    expected_body: str,
) -> None:
    """Frontmatter and body are split with normalized line endings."""
    frontmatter, body = split_frontmatter(text)

    assert frontmatter == expected_frontmatter
    assert body == expected_body


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("# No frontmatter\n", id="no-opening-fence"),
        pytest.param("---\nname: a\nno closing fence\n", id="no-closing-fence"),
        pytest.param("---\nname: a\n--- trailing text\n", id="fence-with-suffix"),
        pytest.param("", id="empty-document"),
    ],
)
def test_split_frontmatter_incomplete_block_returns_none(
    text: str,
) -> None:
    """Documents without a complete frontmatter block yield None."""
    frontmatter, body = split_frontmatter(text)

    assert frontmatter is None
    assert body == text.replace("\r\n", "\n").replace("\r", "\n")


def test_split_frontmatter_empty_frontmatter_is_not_none() -> None:
    """An empty frontmatter block is the empty string, not None."""
    frontmatter, body = split_frontmatter("---\n\n---\nbody\n")

    assert frontmatter == ""
    assert body == "body\n"
