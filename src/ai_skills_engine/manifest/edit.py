"""Lossless YAML value replacement using source positions, without execution."""

import json
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from ai_skills_engine.registry.registry import load_unique_yaml_text


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
    return yaml.dump(
        data,
        Dumper=ManifestDumper,
        sort_keys=False,
        explicit_start=True,
        width=80,
        allow_unicode=True,
    )


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

    def visit(node: Node, before: Any, after: Any) -> None:
        """Collect nonoverlapping source replacements."""
        if before == after:
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
                visit(child, before[key], after[key])
        elif (
            isinstance(node, SequenceNode)
            and isinstance(after, list)
            and isinstance(before, list)
            and len(before) == len(after)
        ):
            for child, previous, desired in zip(node.value, before, after, strict=True):
                visit(child, previous, desired)
        else:
            rendered = (
                yaml.safe_dump(
                    after,
                    default_flow_style=True,
                    sort_keys=False,
                    width=1_000_000,
                    allow_unicode=True,
                )
                .removesuffix("...\n")
                .rstrip("\n")
            )
            if (
                isinstance(after, str)
                and isinstance(node, ScalarNode)
                and node.style == '"'
            ):
                rendered = json.dumps(after, ensure_ascii=False)
            elif (
                isinstance(after, str)
                and isinstance(node, ScalarNode)
                and node.style == "'"
            ):
                rendered = "'" + after.replace("'", "''") + "'"
            if isinstance(node, (MappingNode, SequenceNode)):
                source = text[node.start_mark.index : node.end_mark.index]
                rendered += source[len(source.rstrip()) :]
            changes.append((node.start_mark.index, node.end_mark.index, rendered))

    visit(root, old, data)
    for start, end, replacement in sorted(changes, reverse=True):
        text = text[:start] + replacement + text[end:]
    if load_unique_yaml_text(text=text) != data:
        raise ValueError("Lossless YAML edit did not preserve the requested values")
    return text
