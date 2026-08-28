#!/usr/bin/env python3
"""Shared SKILL.md frontmatter splitting.

Single source of truth for detecting and splitting the YAML frontmatter
block of a ``SKILL.md`` document. Splitting normalizes Windows (CRLF)
and legacy Mac (CR) line endings to Unix newlines first so the ``---``
delimiters are detected reliably.
"""

from __future__ import annotations

import re

from vendor_registry.registry import load_unique_yaml_text

_FENCE_OPEN = "---\n"
_FENCE_CLOSE = "\n---\n"
_NAME_LINE = re.compile(r"^['\"]?name['\"]?\s*:.*$", re.MULTILINE)


def split_frontmatter(
    text: str,
) -> tuple[str | None, str]:
    """Split a document into its YAML frontmatter text and Markdown body.

    Line endings are normalized to Unix newlines before delimiter
    detection. A closing ``---`` at end-of-file without a trailing
    newline is accepted (the body is then empty). Documents without a
    complete frontmatter block yield ``None`` for the frontmatter and
    the whole (newline-normalized) document as the body.

    Args:
        text: Full document content.

    Returns:
        A tuple ``(frontmatter, body)`` where ``frontmatter`` is the
        text between the ``---`` delimiters (excluding the delimiters)
        or ``None`` when no complete frontmatter block is present, and
        ``body`` is the newline-normalized content after the closing
        delimiter (or the whole document when there is no frontmatter).
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith(_FENCE_OPEN):
        return None, normalized
    end = normalized.find(_FENCE_CLOSE, len(_FENCE_OPEN))
    if end != -1:
        return (
            normalized[len(_FENCE_OPEN) : end],
            normalized[end + len(_FENCE_CLOSE) :],
        )
    alt = normalized.find("\n---", len(_FENCE_OPEN))
    if alt != -1 and normalized[alt + len("\n---") :].strip() == "":
        return normalized[len(_FENCE_OPEN) : alt], ""
    return None, normalized


def rewrite_frontmatter_name(*, text: str, name: str) -> str:
    """Rewrite the YAML frontmatter ``name`` field, preserving other keys.

    Line endings are normalized the same way as ``split_frontmatter``. The
    first YAML ``name`` key in the frontmatter block is rewritten, including
    quoted-key forms such as ``"name":``, so bake-time collision renames
    (ADR-0005) stay reviewable diffs instead of a full YAML dump.

    Args:
        text: Full SKILL.md document content.
        name: New skill name to write into frontmatter.

    Returns:
        The document with a rewritten ``name:`` line and Unix newlines.

    Raises:
        TypeError: If frontmatter is not a mapping.
        ValueError: If the document has no complete frontmatter block, no
            ``name:`` field, or duplicate mapping keys.
    """
    frontmatter, body = split_frontmatter(text)
    if frontmatter is None:
        msg = "SKILL.md is missing YAML frontmatter"
        raise ValueError(msg)
    _frontmatter_name(frontmatter=frontmatter)
    updated = _NAME_LINE.sub(repl=f"name: {name}", string=frontmatter, count=1)
    return f"---\n{updated}\n---\n{body}"


def read_frontmatter_name(*, text: str) -> str:
    """Return the YAML frontmatter ``name`` value.

    Args:
        text: Full SKILL.md document content.

    Returns:
        The unquoted ``name`` field.

    Raises:
        TypeError: If frontmatter is not a mapping.
        ValueError: If frontmatter or ``name`` is missing or empty, duplicate
            keys are present, or ``name`` is not a string.
    """
    frontmatter, _body = split_frontmatter(text)
    if frontmatter is None:
        msg = "SKILL.md is missing YAML frontmatter"
        raise ValueError(msg)
    return _frontmatter_name(frontmatter=frontmatter)


def _frontmatter_name(*, frontmatter: str) -> str:
    """Return the unique YAML ``name`` from a frontmatter block.

    Duplicate keys are rejected so last-wins YAML cannot disguise a
    colliding explode name behind an earlier ``name:`` line.

    Args:
        frontmatter: Text between the ``---`` fences.

    Returns:
        The ``name`` field.

    Raises:
        TypeError: If frontmatter is not a mapping.
        ValueError: If YAML is invalid, a key is duplicated, or ``name``
            is missing, empty, or not a string.
    """
    parsed = load_unique_yaml_text(text=frontmatter, source="SKILL.md frontmatter")
    if not isinstance(parsed, dict):
        msg = "SKILL.md frontmatter must be a mapping"
        raise TypeError(msg)
    value = parsed.get("name")
    if not isinstance(value, str) or not value.strip():
        msg = "SKILL.md frontmatter is missing name"
        raise ValueError(msg)
    return value
