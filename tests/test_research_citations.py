"""Keep install-plane evidence locatable without public artifact download links."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest
from assertpy import assert_that
from markdown_it import MarkdownIt
from vendor_registry.safe_tree import iter_markdown_destinations

RUNS = "https://github.com/lgtm-hq/ai-skills/actions/runs"
ARTIFACT_URL = f"{RUNS}/41332673633/artifacts/13094420287"


@pytest.fixture(params=["final", "historical"])
def research_report(
    request: pytest.FixtureRequest,
) -> tuple[str, dict[str, list[str]]]:
    """Load each maintained report with its fixed historical evidence identities.

    Args:
        request: Final or historical report selector.

    Returns:
        Markdown and the original run-to-artifact identities, including repeats.
    """
    # These IDs are the external evidence contract, not generated implementation data.
    if request.param == "final":
        filename = "install-plane-distribution.md"
        identities = {
            "41332673633": [
                "13093629541",
                "13093609553",
                "13093637879",
                "13094033451",
                "13094420287",
                "13094305844",
            ],
            "41332723822": [
                "13093893911",
                "13094072632",
                "13093853917",
                "13093899143",
                "13093114706",
                "13094460630",
            ],
            "41335569949": [
                "13094489784",
                "13094894240",
                "13095216667",
                "13095228033",
                "13095591042",
                "13095635752",
            ]
            * 2,
        }
    else:
        filename = "install-plane-distribution-history.md"
        identities = {
            "41322684015": [
                "13090026458",
                "13089418818",
                "13090220931",
                "13090540153",
                "13090770318",
                "13090425637",
            ],
            "41315907240": [
                "13087556167",
                "13087037043",
                "13087566760",
                "13087157041",
                "13086784287",
                "13087427952",
            ],
            "41316038552": [
                "13087163219",
                "13087845472",
                "13086779149",
                "13086739579",
                "13086894360",
                "13087701539",
            ],
        }
    path = Path(__file__).resolve().parents[1] / "docs/research" / filename
    return path.read_text(encoding="utf-8"), identities


def _artifact_download_links(document: str) -> list[str]:
    """Find actionable artifact destinations while allowing literal evidence IDs.

    Args:
        document: Markdown to inspect without making any requests.

    Returns:
        Artifact download destinations, including unused reference definitions.
    """
    tokens = MarkdownIt("commonmark").enable("table").parse(document)
    candidates = [
        *iter_markdown_destinations(text=document),
        *(token.content for token in tokens if token.type == "html_block"),
        *(
            child.content
            for token in tokens
            for child in token.children or []
            if child.type in {"text", "html_inline"}
        ),
    ]
    return [
        url
        for candidate in candidates
        for url in re.findall(
            r"https?://github\.com/[^/]+/[^/]+/"
            r"(?:actions/runs|suites)/\d+/artifacts/\d+",
            candidate,
        )
    ]


def test_reports_do_not_link_artifact_downloads(
    research_report: tuple[str, dict[str, list[str]]],
) -> None:
    """Public checking must follow run citations rather than artifact downloads."""
    document, _ = research_report
    assert_that(_artifact_download_links(document)).is_empty()


def test_reports_retain_literal_identities_with_matching_run_citations(
    research_report: tuple[str, dict[str, list[str]]],
) -> None:
    """Keep all 42 original artifact occurrences bound to the correct linked runs."""
    document, identities = research_report
    citations = []
    for token in MarkdownIt("commonmark").enable("table").parse(document):
        children = token.children or []
        codes = [child.content for child in children if child.type == "code_inline"]
        if len(codes) == 2 and all(code.isdecimal() for code in codes):
            links = [
                child.attrGet("href") for child in children if child.type == "link_open"
            ]
            citations.append((codes[1], codes[0], tuple(links)))
    expected = [
        (run, artifact, (f"{RUNS}/{run}",))
        for run, artifacts in identities.items()
        for artifact in artifacts
    ]
    assert_that(Counter(citations)).is_equal_to(Counter(expected))


@pytest.mark.parametrize(
    "template",
    [
        "[artifact]({url})",
        "[artifact][evidence]\n\n[evidence]: {url}",
        "[unused]: {url}",
        "<{url}>",
        "| Artifact |\n| --- |\n| [artifact]({url}) |",
        "Evidence: {url}",
        '<a href="{url}">artifact</a>',
        '<div>\n<a href="{url}">artifact</a>\n</div>',
        "![artifact]({url})",
    ],
    ids=[
        "inline",
        "reference",
        "unused-reference",
        "autolink",
        "table",
        "bare-url",
        "inline-html",
        "block-html",
        "image",
    ],
)
def test_artifact_download_regression_controls(template: str) -> None:
    """The original broken destination is detected in each Markdown link form."""
    document = template.format(url=ARTIFACT_URL)
    assert_that(_artifact_download_links(document)).contains(ARTIFACT_URL)


@pytest.mark.parametrize(
    "document",
    [
        f"`13094420287` ([run `41332673633`]({RUNS}/41332673633))",
        f"[run artifacts]({RUNS}/41332673633#artifacts)",
        f"`{ARTIFACT_URL}`",
        f"```text\n{ARTIFACT_URL}\n```",
    ],
    ids=["literal-identities", "run-fragment", "literal-url", "archival-code"],
)
def test_literal_evidence_and_run_citations_remain_allowed(document: str) -> None:
    """The contract preserves exact evidence literals and checked run locators."""
    assert_that(_artifact_download_links(document)).is_empty()
