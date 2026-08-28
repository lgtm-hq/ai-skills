"""Tests for ``scripts/skill_frontmatter.py``."""

from __future__ import annotations

import pytest
from assertpy import assert_that
from skill_frontmatter import (
    read_frontmatter_name,
    rewrite_frontmatter_name,
    split_frontmatter,
)


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

    assert_that(frontmatter).is_equal_to(expected_frontmatter)
    assert_that(body).is_equal_to(expected_body)


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

    assert_that(frontmatter).is_none()
    assert_that(body).is_equal_to(text.replace("\r\n", "\n").replace("\r", "\n"))


def test_split_frontmatter_empty_frontmatter_is_not_none() -> None:
    """An empty frontmatter block is the empty string, not None."""
    frontmatter, body = split_frontmatter("---\n\n---\nbody\n")

    assert_that(frontmatter).is_empty()
    assert_that(body).is_equal_to("body\n")


def test_rewrite_frontmatter_name_preserves_other_keys() -> None:
    """Rename rewrites only the name line and keeps remaining frontmatter."""
    rewritten = rewrite_frontmatter_name(
        text="---\nname: teach\ndescription: Old name.\n---\n\n# Body\n",
        name="teach-example",
    )

    assert_that(rewritten).is_equal_to(
        "---\nname: teach-example\ndescription: Old name.\n---\n\n# Body\n",
    )


def test_rewrite_frontmatter_name_rejects_missing_block() -> None:
    """Documents without frontmatter cannot be renamed at bake time."""
    with pytest.raises(ValueError, match="missing YAML frontmatter"):
        rewrite_frontmatter_name(text="# No fence\n", name="renamed")


def test_rewrite_frontmatter_name_rejects_missing_name_field() -> None:
    """Frontmatter without a name field cannot be renamed at bake time."""
    with pytest.raises(ValueError, match="missing name"):
        rewrite_frontmatter_name(
            text="---\ndescription: No name.\n---\n",
            name="renamed",
        )


def test_read_frontmatter_name_strips_quotes() -> None:
    """Quoted YAML name values are returned unquoted."""
    assert_that(
        read_frontmatter_name(text='---\nname: "branch"\n---\n'),
    ).is_equal_to("branch")


def test_read_frontmatter_name_rejects_duplicate_keys() -> None:
    """Duplicate name keys cannot hide a colliding explode identity."""
    with pytest.raises(ValueError, match="duplicate key"):
        read_frontmatter_name(
            text="---\nname: alpha\nname: branch\n---\n",
        )
