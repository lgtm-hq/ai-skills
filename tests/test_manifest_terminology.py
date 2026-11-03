"""CommonMark vocabulary and glossary tests through the actual lint."""

from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.manifest.terminology import lint_terminology, lint_text


@pytest.mark.parametrize(
    "text",
    [
        "A bundle.",
        "**Com**ponent",
        "A skill\npack",
        "Choose [bundles](catalog.md).",
        "| Term |\n| --- |\n| component |",
        r"Escaped \`bundle\`.",
        "The `literal` component.",
    ],
)
def test_prose_synonyms_are_errors(text: str) -> None:
    """Formatting and wrapped text do not hide genuine prose."""
    assert_that(lint_text(text, location="test")).is_not_empty()


@pytest.mark.parametrize(
    "text",
    [
        "Use `bundle` or ``component `example` ``.",
        "```text\nbundle\n```",
        "    component\n",
        "A bundled runtime.",
        "Read bundles.yaml and vendors.yaml.",
        "com`example`ponent",
    ],
)
def test_literal_code_and_legacy_names_are_exempt(text: str) -> None:
    """Literal names, fences and code boundaries avoid false synonym matches."""
    assert_that(lint_text(text, location="test")).is_empty()


def test_docs_descriptions_and_missing_glossary_term(tmp_path: Path) -> None:
    """Scan nested docs and descriptions without rewriting raw extension evidence."""
    docs = tmp_path / "docs/nested"
    docs.mkdir(parents=True)
    (docs / "example.md").write_text("A bundle is selected.")
    (tmp_path / "docs/glossary.md").write_text("## package\n\nReplaces: bundle.\n")
    findings = lint_terminology(
        tmp_path,
        {
            "packages": [{"description": "A component."}],
            "x-evidence": {"description": "A bundle."},
        },
    )
    assert_that(
        [item.location for item in findings if item.code == "terminology"]
    ).is_equal_to(["docs/nested/example.md", "/packages/0/description"])
    assert_that(
        [item.message for item in findings if item.code == "glossary-term-missing"]
    ).contains("Missing canonical term: capability")


def test_current_repository_passes_production_terminology() -> None:
    """The complete maintained docs and manifest pass the same CLI as CI."""
    assert_that(cli.main(["manifest", "validate", "--terminology"])).is_zero()
