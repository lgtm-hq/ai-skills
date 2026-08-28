#!/usr/bin/env python3
"""Shared SKILL.md frontmatter splitting.

Single source of truth for detecting and splitting the YAML frontmatter
block of a ``SKILL.md`` document. Splitting normalizes Windows (CRLF)
and legacy Mac (CR) line endings to Unix newlines first so the ``---``
delimiters are detected reliably.
"""

from __future__ import annotations

import re

_FENCE_OPEN = "---\n"
_FENCE_CLOSE = "\n---\n"
_NAME_LINE = re.compile(r"^name:\s*.*$", re.MULTILINE)


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

    Line endings are normalized the same way as ``split_frontmatter``. Only
    the first ``name:`` line inside the frontmatter block is replaced so
    bake-time collision renames (ADR-0005) stay reviewable diffs instead of
    a full YAML dump.

    Args:
        text: Full SKILL.md document content.
        name: New skill name to write into frontmatter.

    Returns:
        The document with a rewritten ``name:`` line and Unix newlines.

    Raises:
        ValueError: If the document has no complete frontmatter block or no
            ``name:`` field.
    """
    frontmatter, body = split_frontmatter(text)
    if frontmatter is None:
        msg = "SKILL.md is missing YAML frontmatter"
        raise ValueError(msg)
    if _NAME_LINE.search(frontmatter) is None:
        msg = "SKILL.md frontmatter is missing name"
        raise ValueError(msg)
    updated = _NAME_LINE.sub(repl=f"name: {name}", string=frontmatter, count=1)
    return f"---\n{updated}\n---\n{body}"


def read_frontmatter_name(*, text: str) -> str:
    """Return the YAML frontmatter ``name`` value.

    Args:
        text: Full SKILL.md document content.

    Returns:
        The unquoted ``name`` field.

    Raises:
        ValueError: If frontmatter or ``name`` is missing or empty.
    """
    frontmatter, _body = split_frontmatter(text)
    if frontmatter is None:
        msg = "SKILL.md is missing YAML frontmatter"
        raise ValueError(msg)
    match = _NAME_LINE.search(frontmatter)
    if match is None:
        msg = "SKILL.md frontmatter is missing name"
        raise ValueError(msg)
    _key, _sep, remainder = match.group(0).partition(":")
    value = remainder.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    if not value:
        msg = "SKILL.md frontmatter name must not be empty"
        raise ValueError(msg)
    return value
