"""Guard the ADR index, document structure and local Markdown links."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from assertpy import assert_that
from markdown_it import MarkdownIt
from vendor_registry.safe_tree import (
    _assert_relative_markdown_target,
    _iter_markdown_destinations,
)


def _obsolete_decision_phrases(document: str) -> list[str]:
    """Find banned terms and retired directives despite Markdown and wrapping.

    Args:
        document: ADR text or a candidate clarification.

    Returns:
        Banned terms and obsolete directives present in the normalized text.
    """
    normalized = " ".join(
        re.sub(pattern=r"[-*_`]", repl=" ", string=document.casefold()).split(),
    )
    return [
        phrase
        for phrase in (
            "post v1 backlog",
            "interactive choice deferred to post v1",
            "unconditionally",
            "first wins",
            "event append",
            "wipe and reinstall",
        )
        if phrase in normalized
    ]


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
def index_rows(adr_dir: Path) -> list[tuple[str, str, str]]:
    """Read ADR filenames, titles and statuses from README table rows.

    Args:
        adr_dir: Directory containing the README index.

    Returns:
        Linked filenames with trimmed title and status cells.
    """
    readme = (adr_dir / "README.md").read_text(encoding="utf-8")
    rows = re.findall(
        pattern=(
            r"^\|\s*\[\d{4}\]\((?:\./)?(\d{4}-[^)\s]+\.md)\)"
            r"\s*\|\s*([^|\n]+)\|\s*([^|\n]+)\|\s*$"
        ),
        string=readme,
        flags=re.MULTILINE,
    )
    return [
        (filename, title.strip(), status.strip()) for filename, title, status in rows
    ]


@pytest.fixture(
    params=[
        pytest.param(
            "0001-plugin-canonical-atomic-selection.md",
            id="package-selection",
        ),
        pytest.param(
            "0004-doctor-capability-probe.md",
            id="capability-and-policy",
        ),
        pytest.param(
            "0005-collision-doctrine.md",
            id="identity-and-conflicts",
        ),
    ],
)
def amended_adr(
    adr_dir: Path,
    request: pytest.FixtureRequest,
) -> Path:
    """Locate each ADR amended for the capability engine.

    Args:
        adr_dir: Directory containing the architecture decisions.
        request: Parametrized filename for an amended ADR.

    Returns:
        Path to one of the three amended ADRs.
    """
    filename: str = request.param
    return adr_dir / filename


def test_adr_index_lists_every_adr_once(
    adr_files: list[Path],
    index_rows: list[tuple[str, str, str]],
) -> None:
    """Every numbered ADR has one table link, with no stale entries."""
    filenames = [filename for filename, _, _ in index_rows]

    assert_that(filenames).does_not_contain_duplicates()
    assert_that(filenames).contains_only(*[path.name for path in adr_files])


def test_adr_index_status_matches_document(
    adr_files: list[Path],
    index_rows: list[tuple[str, str, str]],
) -> None:
    """Index statuses preserve amendment dates and omit other status detail."""
    statuses = {filename: status for filename, _, status in index_rows}
    for path in adr_files:
        document = path.read_text(encoding="utf-8")
        declared = re.findall(
            pattern=r"^- Status: (.+)$",
            string=document,
            flags=re.MULTILINE,
        )
        assert_that(declared).described_as(path.name).is_length(1)
        assert_that(statuses).described_as(path.name).contains_key(path.name)
        expected_status = (
            declared[0]
            if declared[0].startswith("Accepted (amended ")
            else declared[0].split(" (", maxsplit=1)[0]
        )
        assert_that(statuses[path.name]).described_as(path.name).is_equal_to(
            expected_status,
        )


def test_amended_adrs_remove_obsolete_decisions(amended_adr: Path) -> None:
    """Reject retired selection, delivery and collision rules, even when wrapped."""
    document = amended_adr.read_text(encoding="utf-8")

    assert_that(_obsolete_decision_phrases(document)).described_as(
        amended_adr.name,
    ).is_empty()


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param(
            "That disable path is post-v1 backlog, not a v1 engine feature.",
            "post v1 backlog",
            id="disable-deferral",
        ),
        pytest.param(
            "Interactive keep-both / pick-one, "
            "with answers persisted as declarations,\n"
            "is **post-v1 backlog** (epic #381 rules).",
            "post v1 backlog",
            id="persisted-choices-deferral",
        ),
        pytest.param(
            "(collision classes 1–3; interactive choice deferred to post-v1)",
            "interactive choice deferred to post v1",
            id="interactive-evidence-deferral",
        ),
        pytest.param(
            "Org denies apply unconditionally.",
            "unconditionally",
            id="owner-banned-term",
        ),
        pytest.param(
            "MCP server keys first-wins, never overwrite.",
            "first wins",
            id="owner-banned-conflict-rule",
        ),
        pytest.param(
            "MCP server keys **first\nwins**, never overwrite.",
            "first wins",
            id="wrapped-conflict-rule",
        ),
        pytest.param(
            "Hooks merge by event\nappend.",
            "event append",
            id="wrapped-event-append",
        ),
        pytest.param(
            'Breaking changes document "wipe and reinstall" in the changelog.',
            "wipe and reinstall",
            id="retired-migration-rule",
        ),
    ],
)
def test_obsolete_decision_phrases_reject_retired_wording(
    document: str,
    expected: str,
) -> None:
    """Actual retired directives and both owner-banned terms remain rejected."""
    assert_that(_obsolete_decision_phrases(document)).is_equal_to([expected])


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(
            "A historical implementation was deferred pending evidence.",
            id="historical-deferral",
        ),
        pytest.param(
            "The issue backlog tracks implementation sequencing.",
            id="issue-backlog",
        ),
        pytest.param(
            "Post-v1 observations do not change these accepted decisions.",
            id="historical-post-v1",
        ),
        pytest.param(
            "Some post-v1 documentation was deferred; see the backlog.",
            id="ordinary-words-together",
        ),
        pytest.param(
            "Interactive collision choices are persisted as declarations.",
            id="accepted-interactive-rule",
        ),
    ],
)
def test_obsolete_decision_phrases_allow_legitimate_wording(document: str) -> None:
    """Ordinary uses of deferral-related words do not restore retired directives."""
    assert_that(_obsolete_decision_phrases(document)).is_empty()


def test_package_selection_supersedes_only_adr_0003_selection(adr_dir: Path) -> None:
    """Supersede ADR 0003's selection consequence while preserving other decisions."""
    document = " ".join(
        (adr_dir / "0001-plugin-canonical-atomic-selection.md")
        .read_text(encoding="utf-8")
        .split(),
    )

    assert_that(document).contains(
        "A **package** is the unit of publication and the default unit of selection.",
        "Absent `include` selects all capabilities; `include: []` selects none.",
        "selectors over qualified capability IDs:",
        "supersedes only the plugin-only selection consequence "
        "of [ADR 0003](./0003-upstream-native-slicing.md)",
        "including its requirement that individual skills join a plugin "
        "or remain unavailable",
        "The package default and capability `include` / `exclude` rules "
        "above apply instead.",
        "ADR 0003's canonical `skills/` authoring layout, upstream-native slicing "
        "and other decisions remain unchanged.",
    )


def test_amended_adrs_record_amendment(amended_adr: Path) -> None:
    """Amended decisions retain acceptance with a dated status and explanation."""
    document = amended_adr.read_text(encoding="utf-8")

    assert_that(document).described_as(amended_adr.name).matches(
        r"(?m)^- Status: Accepted \(amended \d{4}-\d{2}-\d{2}\)$",
    )
    assert_that(document).described_as(amended_adr.name).matches(
        r"(?m)^- Amends: \S[^\n]+$",
    )


def test_amended_adr_index_matches_document(
    amended_adr: Path,
    index_rows: list[tuple[str, str, str]],
) -> None:
    """The index preserves each amended title and the complete dated status."""
    document = amended_adr.read_text(encoding="utf-8")
    title = document.splitlines()[0].split(": ", maxsplit=1)[1]
    status = document.split("- Status: ", maxsplit=1)[1].splitlines()[0]

    assert_that(index_rows).described_as(amended_adr.name).contains(
        (amended_adr.name, title, status),
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


@pytest.fixture(params=["0009", "0010", "0011"])
def accepted_engine_adr(adr_dir: Path, request: pytest.FixtureRequest) -> Path:
    """Locate each accepted engine contract without silently omitting missing ADRs.

    Args:
        adr_dir: Directory containing the architecture decisions.
        request: Required engine ADR number.

    Returns:
        The unique ADR path for that number.
    """
    paths = list(adr_dir.glob(f"{request.param}-*.md"))
    assert_that(paths).described_as(request.param).is_length(1)
    return paths[0]


def test_engine_adr_acceptance_and_index(
    accepted_engine_adr: Path,
    index_rows: list[tuple[str, str, str]],
) -> None:
    """New contracts have exact Accepted status, dated metadata and matching titles."""
    document = accepted_engine_adr.read_text(encoding="utf-8")
    number = accepted_engine_adr.name[:4]
    assert_that(document).matches(rf"\A# ADR {number}: \S[^\n]+\n")
    assert_that(document).matches(r"(?m)^- Status: Accepted$")
    assert_that(document).matches(r"(?m)^- Date: \d{4}-\d{2}-\d{2}$")
    title = document.splitlines()[0].split(": ", maxsplit=1)[1]
    assert_that(index_rows).contains((accepted_engine_adr.name, title, "Accepted"))


def test_engine_adrs_cross_link_contracts(accepted_engine_adr: Path) -> None:
    """Each accepted contract links the glossary and the other two contracts."""
    document = accepted_engine_adr.read_text(encoding="utf-8")
    targets = set(_iter_markdown_destinations(text=document))
    assert_that(targets).contains("../glossary.md")
    for number in range(9, 12):
        if f"{number:04d}" != accepted_engine_adr.name[:4]:
            assert_that(
                any(target.startswith(f"./{number:04d}-") for target in targets),
            ).described_as(
                f"{accepted_engine_adr.name} links ADR {number:04d}"
            ).is_true()


def test_adr_internal_links_resolve(adr_dir: Path, adr_files: list[Path]) -> None:
    """Reuse the offline bake link checks with the repository as containment root."""
    for path in [*adr_files, adr_dir / "README.md"]:
        for target in _iter_markdown_destinations(
            text=path.read_text(encoding="utf-8")
        ):
            _assert_relative_markdown_target(
                raw_target=target,
                file_path=path,
                root=adr_dir.parents[1],
            )
