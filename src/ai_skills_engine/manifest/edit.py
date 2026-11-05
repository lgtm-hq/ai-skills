"""Lossless YAML value replacement using source positions, without execution."""

import json
import re
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from ai_skills_engine.manifest.scalars import quote_vendor_scalars
from ai_skills_engine.registry.registry import load_unique_yaml_text

# Characters YAML cannot carry literally; double-quoted scalars escape them.
_UNPRINTABLE = re.compile("[\x7f-\x9f\ud800-\udfff￾￿]")


class ManifestDumper(yaml.SafeDumper):
    """Indent list items and retain multiline formatting templates literally."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        """Indent lists consistently with the legacy registries.

        Args:
            flow: Whether the emitter is in a flow collection.
            indentless: Ignored so block lists always indent.
        """
        super().increase_indent(flow=flow, indentless=False)


def _string(dumper: ManifestDumper, value: str) -> yaml.nodes.ScalarNode:
    """Emit multiline templates as literal scalars.

    Args:
        dumper: Safe manifest emitter.
        value: String value.

    Returns:
        YAML string node.
    """
    multiline = "\n" in value
    style = (
        ('"' if any(len(line) > 80 for line in value.splitlines()) else "|")
        if multiline
        else None
    )
    if not multiline and len(value) > 50 and " " in value:
        style = ">"
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


ManifestDumper.add_representer(str, _string)


def dump_document(data: object) -> str:
    """Render a new manifest deterministically.

    Args:
        data: JSON-compatible mapping.

    Returns:
        Safe YAML with indented lists.
    """
    return quote_vendor_scalars(
        data=data,
        text=yaml.dump(
            data,
            Dumper=ManifestDumper,
            sort_keys=False,
            explicit_start=True,
            width=80,
            allow_unicode=True,
        ),
    )


def _same_value(before: object, after: object) -> bool:
    """Compare JSON-compatible values without conflating scalar types.

    Args:
        before: Parsed source value.
        after: Authoritative desired value.

    Returns:
        Whether values and their recursively nested scalar types match.
    """
    if type(before) is not type(after):
        return False
    if isinstance(before, dict) and isinstance(after, dict):
        return before.keys() == after.keys() and all(
            _same_value(before=value, after=after[key]) for key, value in before.items()
        )
    if isinstance(before, list) and isinstance(after, list):
        return len(before) == len(after) and all(
            _same_value(before=previous, after=desired)
            for previous, desired in zip(before, after, strict=True)
        )
    return before == after


def patch_document(*, text: str, data: object) -> str:
    """Replace changed values while preserving unchanged source bytes.

    Matching mapping keys and list positions are visited recursively. A changed
    collection shape is serialized at that node only. Templates supply layout,
    comments and quotes; all semantic values come from ``data``.

    Args:
        text: Original YAML formatting template.
        data: Authoritative desired document.

    Returns:
        Deterministically patched YAML.

    Raises:
        ValueError: If YAML is malformed or an alias would make edits ambiguous.
    """
    old = load_unique_yaml_text(text=text)
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    if root is None:
        return dump_document(data)
    changes: list[tuple[int, int, str]] = []
    visited: set[int] = set()

    def visit(node: Node, before: Any, after: Any, flow: bool = False) -> None:
        """Collect nonoverlapping source replacements."""
        if _same_value(before=before, after=after):
            return
        if id(node) in visited:
            raise ValueError("Cannot edit aliased YAML values losslessly")
        visited.add(id(node))
        if (
            isinstance(node, MappingNode)
            and isinstance(before, dict)
            and isinstance(after, dict)
            and before.keys() == after.keys()
        ):
            for key_node, child in node.value:
                key = key_node.value
                if key not in before or key not in after:
                    # A key YAML resolves to a non-string (``on``, ``1``, ``null``)
                    # has no lossless source mapping; fail closed, not KeyError.
                    raise ValueError(
                        "Cannot edit YAML mappings with non-string keys losslessly"
                    )
                visit(child, before[key], after[key], flow or node.flow_style)
        elif (
            isinstance(node, SequenceNode)
            and isinstance(after, list)
            and isinstance(before, list)
            and len(before) == len(after)
        ):
            for child, previous, desired in zip(node.value, before, after, strict=True):
                visit(child, previous, desired, flow or node.flow_style)
        else:
            start = node.start_mark.index
            line_start = text.rfind("\n", 0, start) + 1
            prefix = text[line_start:start]
            indent = node.start_mark.column
            collection = isinstance(after, (dict, list))
            inline = collection and not flow and prefix.strip() not in {"", "-"}
            if inline:
                indent = len(prefix) - len(prefix.lstrip()) + 2
                if prefix.lstrip().startswith("- "):
                    indent += 2
                while start > line_start and text[start - 1] == " ":
                    start -= 1
            rendered = (
                yaml.dump(
                    after,
                    Dumper=(
                        ManifestDumper if collection and not flow else yaml.SafeDumper
                    ),
                    default_flow_style=flow or not collection,
                    sort_keys=False,
                    width=max(20, 80 - indent),
                    # Escape Unicode line separators inside new flow collections:
                    # YAML folds literal NEL/LS/PS, including in quoted scalars.
                    allow_unicode=not flow,
                )
                .removesuffix("...\n")
                .rstrip("\n")
            )
            rendered = rendered.replace("\n", "\n" + " " * indent)
            if flow and isinstance(after, str):
                # Inside a flow collection, `,`, `[`, `]`, `{` and `}` end a plain
                # scalar: render the value as a flow-sequence item instead.
                rendered = yaml.dump(
                    [after],
                    Dumper=yaml.SafeDumper,
                    default_flow_style=True,
                    width=float("inf"),
                    allow_unicode=False,
                ).rstrip("\n")[1:-1]
            if collection:
                if inline:
                    rendered = "\n" + " " * indent + rendered
            elif isinstance(after, str) and (
                isinstance(node, ScalarNode)
                and (
                    node.style == '"'
                    or (node.style == "'" and _UNPRINTABLE.search(after) is not None)
                )
                or any(char in after for char in "\n\r\x85\u2028\u2029")
            ):
                # YAML folds a literal NEL even inside double quotes, and rejects
                # DEL, C1 controls, surrogates and U+FFFE/U+FFFF in any scalar.
                rendered = _UNPRINTABLE.sub(
                    lambda match: f"\\u{ord(match.group()):04x}",
                    json.dumps(after, ensure_ascii=False),
                )
            elif (
                isinstance(after, str)
                and isinstance(node, ScalarNode)
                and node.style == "'"
            ):
                rendered = "'" + after.replace("'", "''") + "'"
            if isinstance(node, (MappingNode, SequenceNode)) or (
                isinstance(node, ScalarNode) and node.style in {"|", ">"}
            ):
                source = text[node.start_mark.index : node.end_mark.index]
                rendered += source[len(source.rstrip()) :]
            changes.append((start, node.end_mark.index, rendered))

    visit(root, old, data)
    for start, end, replacement in sorted(changes, reverse=True):
        text = text[:start] + replacement + text[end:]
    text = quote_vendor_scalars(text=text, data=data)
    if not _same_value(before=load_unique_yaml_text(text=text), after=data):
        raise ValueError("Lossless YAML edit did not preserve the requested values")
    return text
