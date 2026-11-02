"""Guard the engine vocabulary, including retired aliases in ADR prose."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

import pytest
from assertpy import assert_that
from markdown_it import MarkdownIt
from markdown_it.token import Token
from vendor_registry.safe_tree import iter_markdown_destinations


def _normalized(text: str) -> str:
    """Normalize case and whitespace for vocabulary comparisons.

    Args:
        text: A term, alias or prose fragment.

    Returns:
        Case-folded text with whitespace collapsed.
    """
    return " ".join(text.casefold().split())


def _glossary_entries(document: str) -> list[tuple[str, list[str]]]:
    """Read one alias declaration per level-two glossary entry.

    Args:
        document: Glossary Markdown with plain term headings.

    Returns:
        Ordered terms and aliases, retaining duplicates for validation.
    """
    tokens = MarkdownIt("commonmark").parse(document)
    entries = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.tag != "h2":
            continue
        term = _normalized(tokens[index + 1].content)
        end = next(
            (
                offset
                for offset in range(index + 3, len(tokens))
                if tokens[offset].type == "heading_open"
                and tokens[offset].tag in {"h1", "h2"}
            ),
            len(tokens),
        )
        declarations = [
            match.group(1)
            for child in tokens[index + 3 : end]
            if child.type == "inline"
            and (match := re.fullmatch(r"Replaces: (.+)\.", child.content))
        ]
        assert_that(declarations).described_as(term).is_length(1)
        aliases = (
            []
            if declarations[0] == "none"
            else [_normalized(alias) for alias in declarations[0].split(",")]
        )
        entries.append((term, aliases))
    assert_that(entries).is_not_empty()
    return entries


def _prose(tokens: Sequence[Token]) -> str:
    """Collect rendered text while separating inline code from adjacent prose.

    Args:
        tokens: CommonMark tokens, including nested inline children.

    Returns:
        Prose without code spans, fences or indented code blocks.
    """
    parts = []
    for token in tokens:
        if token.children:
            parts.append(_prose(token.children))
        elif token.type in {"text", "html_inline", "html_block"}:
            parts.append(token.content)
        elif token.type == "code_inline":
            parts.append("\0")
        elif token.type in {"softbreak", "hardbreak"} or token.block:
            parts.append(" ")
    return "".join(parts)


def _retired_aliases(*, document: str, aliases: list[str]) -> list[str]:
    """Find retired whole terms in prose, including formatted and wrapped text.

    Args:
        document: ADR Markdown to inspect.
        aliases: Retired terms from the glossary.

    Returns:
        Aliases appearing outside code, without matching substrings.
    """
    prose = _normalized(
        _prose(MarkdownIt("commonmark").enable("table").parse(document))
        + " "
        + " ".join(iter_markdown_destinations(text=document)),
    )
    return [
        alias
        for alias in aliases
        if re.search(pattern=rf"(?<!\w){re.escape(alias)}(?!\w)", string=prose)
    ]


@pytest.fixture
def glossary_entries() -> list[tuple[str, list[str]]]:
    """Load the canonical glossary without collapsing duplicate entries.

    Returns:
        Terms and their declared aliases from the committed Markdown.
    """
    path = Path(__file__).resolve().parents[1] / "docs/glossary.md"
    return _glossary_entries(path.read_text(encoding="utf-8"))


@pytest.fixture
def engine_adrs() -> list[Path]:
    """Locate the complete engine ADR range covered by the alias contract.

    Returns:
        All four ADR paths, including the accepted runtime decision.
    """
    root = Path(__file__).resolve().parents[1] / "docs/adr"
    paths = sorted(
        path for number in range(8, 12) for path in root.glob(f"{number:04d}-*.md")
    )
    assert_that([path.name[:4] for path in paths]).is_equal_to(
        ["0008", "0009", "0010", "0011"],
    )
    return paths


def test_glossary_terms_and_aliases_are_unique(
    glossary_entries: list[tuple[str, list[str]]],
) -> None:
    """Every concept and retired term has one unambiguous canonical spelling."""
    terms = [term for term, _ in glossary_entries]
    aliases = [alias for _, replaced in glossary_entries for alias in replaced]

    assert_that(terms).does_not_contain_duplicates().does_not_contain("")
    assert_that(aliases).does_not_contain_duplicates().does_not_contain("", "none")
    assert_that(set(aliases).intersection(terms)).is_empty()
    assert_that(terms).contains(
        "catalog",
        "package",
        "capability",
        "resource",
        "plugin",
        "role",
        "dialect",
        "adapter",
        "artifact",
        "mode",
        "scope",
        "vendor",
        "consumer",
        "re-exporter",
        "origin",
        "lineage",
        "lock",
        "receipt",
        "policy",
        "trust grant",
        "evidence",
        "tier",
        "cell state",
    )
    replacements = {
        alias: term for term, replaced in glossary_entries for alias in replaced
    }
    assert_that(replacements).contains_entry(
        {"bundle": "package"},
        {"component": "capability"},
    )


def test_engine_adrs_use_no_retired_aliases(
    glossary_entries: list[tuple[str, list[str]]],
    engine_adrs: list[Path],
) -> None:
    """Inspect every engine ADR's prose without exempting the runtime ADR."""
    aliases = [alias for _, replaced in glossary_entries for alias in replaced]
    for path in engine_adrs:
        assert_that(
            _retired_aliases(
                document=path.read_text(encoding="utf-8"),
                aliases=aliases,
            ),
        ).described_as(path.name).is_empty()


@pytest.mark.parametrize(
    "document",
    [
        "A BUNDLE is selected.",
        "## Components\n\nThe old heading is also prose.",
        "Choose **com**ponent.",
        "- Select a [bundle](artifact.md).",
        "| Term |\n| --- |\n| component |",
        "The old\nname is retired.",
        "A `capability` replaces a bundle.",
        r"An escaped \`bundle\` is prose.",
        "See [canonical vocabulary](component.md).",
        "[unused]: bundle.md\n",
        "<!-- component -->",
    ],
    ids=[
        "case",
        "heading-plural",
        "emphasis",
        "link-label",
        "table",
        "wrapped-phrase",
        "prose-beside-code",
        "escaped-backticks",
        "link-destination",
        "unused-reference",
        "html-comment",
    ],
)
def test_alias_scan_rejects_retired_prose(document: str) -> None:
    """Formatting, wrapping and nearby code never exempt visible retired terms."""
    assert_that(
        _retired_aliases(
            document=document,
            aliases=["bundle", "components", "component", "old name"],
        ),
    ).is_not_empty()


@pytest.mark.parametrize(
    "document",
    [
        "A bundled runtime has componentized internals.",
        "Use `bundle` and ``component `example` `` as literal input.",
        "```text\nbundle\n```\n\n~~~\ncomponent\n~~~",
        "    bundle\n    component\n",
        "com`example`ponent is not a retired term.",
    ],
    ids=[
        "word-boundaries",
        "inline-delimiters",
        "fences",
        "indented-code",
        "code-boundary",
    ],
)
def test_alias_scan_allows_code_and_distinct_words(document: str) -> None:
    """Only code and distinct words escape whole-term alias matching."""
    assert_that(
        _retired_aliases(document=document, aliases=["bundle", "component"]),
    ).is_empty()


def test_glossary_parser_preserves_duplicate_terms_and_aliases() -> None:
    """Case and whitespace normalization must expose rather than erase duplicates."""
    entries = _glossary_entries(
        "## Package\n\nReplaces: bundle.\n\n"
        "## PACKAGE\n\nReplaces: Bundle, bundle.\n",
    )
    assert_that(entries).is_equal_to(
        [("package", ["bundle"]), ("package", ["bundle", "bundle"])],
    )


@pytest.mark.parametrize(
    "document",
    [
        "# No entries\n",
        "## package\n\nMissing aliases.\n",
        "## package\n\nReplaces: bundle.\n\nReplaces: component.\n",
    ],
    ids=["empty", "missing-declaration", "duplicate-declaration"],
)
def test_glossary_parser_rejects_missing_or_ambiguous_declarations(
    document: str,
) -> None:
    """A malformed glossary cannot silently disable alias checks."""
    with pytest.raises(AssertionError):
        _glossary_entries(document)
