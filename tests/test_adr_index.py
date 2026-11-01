"""Guard the ADR index, document structure and local Markdown links."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from assertpy import assert_that
from markdown_it import MarkdownIt
from vendor_registry.safe_tree import validate_internal_references


@pytest.fixture
def adr_dir() -> Path:
    """Return the repository's architecture decision directory.

    Returns:
        Directory containing the ADRs and their README index.
    """
    return Path(__file__).resolve().parents[1] / "docs" / "adr"


@pytest.fixture
def adr_files(adr_dir: Path) -> list[Path]:
    """Find numbered ADRs without silently accepting an empty directory.

    Args:
        adr_dir: Directory containing the architecture decisions.

    Returns:
        Numbered Markdown files in filename order.
    """
    paths = sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert_that(paths).described_as(str(adr_dir)).is_not_empty()
    return paths


@pytest.fixture
def index_rows(adr_dir: Path) -> list[tuple[str, str]]:
    """Read ADR filenames and statuses from README table rows.

    Args:
        adr_dir: Directory containing the README index.

    Returns:
        Linked filenames and trimmed status cells.
    """
    readme = (adr_dir / "README.md").read_text(encoding="utf-8")
    rows = re.findall(
        pattern=(
            r"^\|\s*\[\d{4}\]\((?:\./)?(\d{4}-[^)\s]+\.md)\)"
            r"\s*\|[^|\n]+\|\s*([^|\n]+)\|\s*$"
        ),
        string=readme,
        flags=re.MULTILINE,
    )
    return [(filename, status.strip()) for filename, status in rows]


def test_adr_index_lists_every_adr_once(
    adr_files: list[Path],
    index_rows: list[tuple[str, str]],
) -> None:
    """Every numbered ADR has one table link, with no stale entries."""
    filenames = [filename for filename, _ in index_rows]

    assert_that(filenames).does_not_contain_duplicates()
    assert_that(filenames).contains_only(*[path.name for path in adr_files])


def test_adr_index_status_matches_document(
    adr_files: list[Path],
    index_rows: list[tuple[str, str]],
) -> None:
    """Index statuses match document statuses, allowing parenthetical detail."""
    statuses = dict(index_rows)
    for path in adr_files:
        document = path.read_text(encoding="utf-8")
        declared = re.findall(
            pattern=r"^- Status: (.+)$",
            string=document,
            flags=re.MULTILINE,
        )
        assert_that(declared).described_as(path.name).is_length(1)
        assert_that(statuses).described_as(path.name).contains_key(path.name)
        status_prefix = declared[0].split(" (", maxsplit=1)[0]
        assert_that(statuses[path.name]).described_as(path.name).is_equal_to(
            status_prefix,
        )


def test_adrs_have_required_sections(adr_files: list[Path]) -> None:
    """Each ADR has actual level-two Context, Decision and Consequences headings."""
    parser = MarkdownIt("commonmark")
    for path in adr_files:
        tokens = parser.parse(path.read_text(encoding="utf-8"))
        headings = [
            tokens[index + 1].content
            for index, token in enumerate(tokens)
            if token.type == "heading_open" and token.tag == "h2"
        ]
        assert_that(headings).described_as(path.name).contains(
            "Context",
            "Decision",
            "Consequences",
        )


def test_adr_internal_links_resolve(adr_dir: Path) -> None:
    """Validate local inline and reference links offline using the bake checker."""
    validate_internal_references(root=adr_dir)
