#!/usr/bin/env python3
"""Shared SKILL.md frontmatter splitting.

Single source of truth for detecting and splitting the YAML frontmatter
block of a ``SKILL.md`` document. Splitting normalizes Windows (CRLF)
and legacy Mac (CR) line endings to Unix newlines first so the ``---``
delimiters are detected reliably.
"""

from __future__ import annotations

_FENCE_OPEN = "---\n"
_FENCE_CLOSE = "\n---\n"


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
