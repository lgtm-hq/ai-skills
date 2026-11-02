"""CommonMark prose terminology lint with literal and archival boundaries."""

import re
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token

from ai_skills_engine.manifest.diagnostic import Diagnostic

SYNONYMS = {
    "bundle": "package",
    "bundles": "package",
    "component": "capability",
    "components": "capability",
    "skill pack": "package",
    "skill packs": "package",
}
CANONICAL_TERMS = (
    "catalog",
    "package",
    "capability",
    "resource",
    "plugin",
    "role",
    "dialect",
    "host",
    "adapter",
    "artifact",
    "mode",
    "scope",
    "vendor",
    "consumer",
    "re-exporter",
    "origin",
    "lineage",
    "provenance",
    "lock",
    "receipt",
    "policy",
    "trust grant",
    "evidence",
    "tier",
    "parity cell",
    "cell state",
    "projection",
    "bake",
    "journal",
    "generation",
    "publisher",
    "closure",
    "attestation",
)


def _prose(tokens: list[Token]) -> str:
    """Collect visible prose while separating code spans from adjacent words.

    Args:
        tokens: CommonMark token tree.

    Returns:
        Prose including formatted text, excluding literal code and HTML data.
    """
    parts = []
    for token in tokens:
        if token.children:
            parts.append(_prose(token.children))
        elif token.type == "text":
            parts.append(token.content)
        elif token.type == "code_inline":
            parts.append("\0")
        elif token.type in {"softbreak", "hardbreak"} or token.block:
            parts.append(" ")
    return "".join(parts)


def lint_text(text: str, *, location: str) -> list[Diagnostic]:
    """Find retired whole terms in genuine prose, including wrapped phrases.

    Args:
        text: Markdown text or description.
        location: Source path or manifest JSON pointer.

    Returns:
        Terminology errors with canonical replacements.
    """
    prose = " ".join(
        _prose(MarkdownIt("commonmark").enable("table").parse(text)).casefold().split()
    )
    prose = re.sub(r"\b(?:bundles|vendors)\.ya?ml\b", "", prose)
    return [
        Diagnostic("terminology", location, f"Use {canonical!r} instead of {alias!r}")
        for alias, canonical in SYNONYMS.items()
        if re.search(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", prose)
    ]


def lint_terminology(repo_root: Path, data: dict[str, Any]) -> list[Diagnostic]:
    """Scan maintained docs and descriptions and require the whole glossary.

    Glossary alias declarations teach the lint's vocabulary and are not uses.
    Raw evidence snapshots live outside docs and remain immutable. Accepted ADRs
    are scanned as prose; their decisions receive no blanket exemption.

    Args:
        repo_root: Repository with docs/glossary.md.
        data: Manifest mapping; opaque extensions are never linted.

    Returns:
        Vocabulary diagnostics.
    """
    findings: list[Diagnostic] = []
    glossary = repo_root / "docs" / "glossary.md"
    text = glossary.read_text(encoding="utf-8") if glossary.is_file() else ""
    headings = {
        match.casefold() for match in re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    }
    findings.extend(
        Diagnostic(
            "glossary-term-missing",
            "docs/glossary.md",
            f"Missing canonical term: {term}",
        )
        for term in CANONICAL_TERMS
        if term not in headings
    )
    for path in sorted((repo_root / "docs").rglob("*.md")):
        document = path.read_text(encoding="utf-8")
        if path == glossary:
            document = re.sub(r"^Replaces:.*$", "", document, flags=re.MULTILINE)
        findings.extend(
            lint_text(document, location=path.relative_to(repo_root).as_posix())
        )

    def descriptions(value: Any, location: str = "") -> None:
        """Walk named fields, never entering extension payloads."""
        if isinstance(value, dict):
            for key, item in value.items():
                if key.startswith("x-"):
                    continue
                if key == "description" and isinstance(item, str):
                    findings.extend(lint_text(item, location=f"{location}/{key}"))
                descriptions(item, f"{location}/{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                descriptions(item, f"{location}/{index}")

    descriptions(data)
    return findings
