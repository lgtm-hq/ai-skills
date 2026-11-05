"""Rewrite proven CommonMark destinations and explicitly declared scalar paths."""

import json
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import yaml
from markdown_it.helpers import parseLinkDestination
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from ai_skills_engine.registry.safe_tree import (
    _COMMONMARK,
    _local_markdown_path,
    contained_path,
    iter_markdown_destinations,
    walk_files,
)

_CANDIDATES = re.compile(r"\]\(|\]:")
_RELATIVE = re.compile(r"""(?<![\w/])(?:\.\.?/)+[^\s<>"'`\[\](){}]+""")


def resource_path(raw: str) -> str | None:
    """Retain literal filesystem spelling in an explicitly declared scalar.

    Percent escapes, query and fragment characters are ordinary filename bytes.
    URL operands retain the existing remote/unsafe scheme policy: a value that
    starts with ``letters:`` or ``//`` is read as a URL, so remote URLs stay
    unchanged and other schemes are rejected. Spell a colon-bearing relative
    filename with a leading ``./`` (``./notes:v1.md``).

    Args:
        raw: Parsed JSON/YAML/frontmatter scalar.

    Returns:
        Unmodified local operand, or None for empty/remote operands.

    Raises:
        ValueError: For unsafe schemes, backslashes or NUL bytes.
    """
    if "\\" in raw or "\0" in raw:
        raise ValueError(f"Unsafe resource path: {raw}")
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw) or raw.startswith("//"):
        # Share scheme validation only; filesystem strings never pass its decoder.
        _local_markdown_path(raw_target=raw)
        return None
    return raw or None


def validate_artifact_references(*, root: Path) -> None:
    """Validate emitted artifact links to existing files or directories.

    Args:
        root: Isolated capability output tree, including its resource copies.

    Raises:
        ValueError: For missing, unsafe or escaping local targets.
    """
    for path in walk_files(root=root):
        if path.suffix.lower() not in {".md", ".markdown", ".mdc"}:
            continue
        for raw in iter_markdown_destinations(text=path.read_text(encoding="utf-8")):
            local = _local_markdown_path(raw_target=raw)
            if local is None:
                continue
            target = contained_path(path=path.parent / local, root=root)
            if not target.is_file() and not target.is_dir():
                raise ValueError(f"internal reference missing: {raw}")


def markdown_body(text: str) -> tuple[str, str]:
    """Separate frontmatter while preserving the original source bytes.

    Args:
        text: Original UTF-8 text.

    Returns:
        Unmodified prefix and Markdown body.
    """
    match = re.match(r"\A---\r?\n.*?\r?\n---(?:\r?\n|\Z)", text, flags=re.DOTALL)
    return (text[: match.end()], text[match.end() :]) if match else ("", text)


def rewrite_markdown(*, text: str, replace: Callable[[str], str | None]) -> str:
    """Edit destinations only when a CommonMark reparse proves their role.

    A candidate in prose, a fence or a code span cannot pass this proof. Reference
    definitions can affect multiple tokens. Everything outside the destination
    span, including indentation, titles, prose and code, stays byte-for-byte.

    Args:
        text: Original Markdown.
        replace: Return a relocated destination or None to preserve it.

    Returns:
        Source with only authenticated destination spans changed.
    """
    prefix, body = markdown_body(text)
    for match in reversed(list(_CANDIDATES.finditer(body))):
        start = match.end()
        while start < len(body) and body[start].isspace():
            start += 1
        parsed = parseLinkDestination(body, start, len(body))
        if not parsed.ok:
            continue
        old = _COMMONMARK.normalizeLink(parsed.str)
        new = replace(old)
        if new is None or new == old:
            continue
        candidate = body[:start] + "<" + new + ">" + body[parsed.pos :]
        before = Counter(iter_markdown_destinations(text=body))
        after = Counter(iter_markdown_destinations(text=candidate))
        removed, added = before - after, after - before
        if set(removed) == {old} and set(added) == {new} and removed[old] == added[new]:
            body = candidate
    return prefix + body


def _pointer(*, node: Node, pointer: str) -> ScalarNode:
    """Locate a declared scalar via a strict JSON pointer in parsed YAML.

    Args:
        node: YAML/JSON document root.
        pointer: RFC 6901 pointer.

    Returns:
        Scalar node with source positions.

    Raises:
        ValueError: If the pointer is invalid, ambiguous, missing or not a scalar.
    """
    if not pointer.startswith("/"):
        raise ValueError("Resource path fields require nonempty JSON pointers")
    current = node
    for encoded in pointer[1:].split("/"):
        if re.search(r"~(?![01])", encoded):
            raise ValueError("Invalid resource path pointer escape")
        part = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, MappingNode):
            matches = [
                value
                for key, value in current.value
                if isinstance(key, ScalarNode) and key.value == part
            ]
            if len(matches) != 1:
                raise ValueError("Missing or ambiguous declared resource path field")
            current = matches[0]
        elif (
            isinstance(current, SequenceNode)
            and part.isdecimal()
            and str(int(part)) == part
            and int(part) < len(current.value)
        ):
            current = current.value[int(part)]
        else:
            raise ValueError("Missing declared resource path field")
    if not isinstance(current, ScalarNode) or current.tag != "tag:yaml.org,2002:str":
        raise ValueError("Declared resource path field must be a string scalar")
    return current


def _quoted(value: str) -> str:
    """Serialize a double-quoted scalar that JSON and YAML both reparse exactly.

    Supplementary characters stay literal: YAML decodes JSON surrogate-pair
    escapes as two lone surrogates. Nonprintable BMP characters, including NEL
    and the Unicode line/paragraph separators, use escapes valid in both.

    Args:
        value: Replacement scalar value.

    Returns:
        Quoted scalar spelling.

    Raises:
        ValueError: If either parser would not return the exact value.
    """
    quoted = "".join(
        (
            f"\\u{ord(character):04x}"
            if ord(character) <= 0xFFFF and not character.isprintable()
            else character
        )
        for character in json.dumps(value, ensure_ascii=False)
    )
    if yaml.safe_load(quoted) != value or json.loads(quoted) != value:
        raise ValueError("Resource path field cannot be serialized exactly")
    return quoted


def rewrite_fields(
    *,
    text: str,
    pointers: tuple[str, ...],
    markdown: bool,
    replace: Callable[[str], str | None],
) -> str:
    """Change declared JSON/YAML/frontmatter scalars without dumping the document.

    Args:
        text: Original UTF-8 source.
        pointers: Explicit consumer/publisher-declared path field locations.
        markdown: Whether pointers address the YAML frontmatter.
        replace: Relocation function for each declared scalar path.

    Returns:
        Source with exact scalar spans replaced, retaining every other byte.

    Raises:
        ValueError: For missing fields, aliases, tags or unsupported scalar syntax.
    """
    prefix, _body = markdown_body(text) if markdown else (text, "")
    offset = prefix.index("\n") + 1 if markdown and prefix else 0
    source = prefix[offset : prefix.rfind("---")] if markdown and prefix else prefix
    if markdown and not prefix:
        raise ValueError("Declared resource path requires YAML frontmatter")
    try:
        tokens = tuple(yaml.scan(source))
        root = yaml.compose(source, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        raise ValueError("Malformed declared resource path document") from error
    if any(
        isinstance(token, (yaml.AliasToken, yaml.AnchorToken, yaml.TagToken))
        for token in tokens
    ):
        raise ValueError(
            "Resource path fields cannot use YAML aliases, anchors or tags"
        )
    if root is None:
        raise ValueError("Empty resource path document")
    edits = []
    for pointer in pointers:
        node = _pointer(node=root, pointer=pointer)
        if node.style in {"|", ">"}:
            raise ValueError("Resource path fields require ordinary string scalars")
        new = replace(node.value)
        if new is not None and new != node.value:
            edits.append(
                (
                    node.start_mark.index + offset,
                    node.end_mark.index + offset,
                    _quoted(new),
                )
            )
    for start, end, value in sorted(edits, reverse=True):
        text = text[:start] + value + text[end:]
    return text


def opaque_references(*, text: str, replace: Callable[[str], str | None]) -> bool:
    """Detect relative references left in prose/code, never rewrite them.

    Args:
        text: Text after structural rewrites.
        replace: Relocation function for source-coordinate operands.

    Returns:
        Whether a demonstrated path requirement would move or escape.
    """
    if any(
        marker in text
        for marker in (
            "${CLAUDE_PLUGIN_ROOT}",
            "$CLAUDE_PLUGIN_ROOT",
            "${CURSOR_PLUGIN_ROOT}",
        )
    ):
        return True
    return any(
        replace(match.group().rstrip(".,;:")) is not None
        for match in _RELATIVE.finditer(text)
    )
