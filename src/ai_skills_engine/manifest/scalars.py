"""Offline string boundaries of Renovate's pinned YAML scalar resolvers.

Renovate 44.206.2 calls yaml 2.9.1 with strict:false and the default 1.2 core
schema, or yaml-1.1 when a document directive selects it. These are the complete
implicit non-string resolver classes, not a list of known ambiguous values.
The production differential gate exercises the actual pinned parser/updater.
"""

import json
import re
from collections.abc import Iterator

import yaml
from yaml.events import DocumentStartEvent, ScalarEvent
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from yaml.tokens import AnchorToken, ScalarToken, TagToken

_COMMON = (
    r"(?:~|[Nn]ull|NULL)?",
    r"[-+]?\.(?:inf|Inf|INF)|\.nan|\.NaN|\.NAN",
)
_CORE = re.compile(
    "|".join(
        (
            *_COMMON,
            r"[Tt]rue|TRUE|False|false|FALSE",
            r"0o[0-7]+|[-+]?[0-9]+|0x[0-9a-fA-F]+",
            r"[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)[eE][-+]?[0-9]+",
            r"[-+]?(?:\.[0-9]+|[0-9]+\.[0-9]*)",
        )
    )
)
_YAML11 = re.compile(
    "|".join(
        (
            *_COMMON,
            r"Y|y|[Yy]es|YES|[Tt]rue|TRUE|[Oo]n|ON",
            r"N|n|[Nn]o|NO|False|false|FALSE|[Oo]ff|OFF",
            r"[-+]?(?:0b[0-1_]+|0[0-7_]+|[0-9][0-9_]*|0x[0-9a-fA-F_]+)",
            r"[-+]?(?:[0-9][0-9_]*)?(?:\.[0-9_]*)?[eE][-+]?[0-9]+",
            r"[-+]?(?:[0-9][0-9_]*)?\.[0-9_]*",
            r"[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+(?:\.[0-9_]*)?",
            (
                r"[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}"
                r"(?:(?:t|T|[ \t]+)[0-9]{1,2}:[0-9]{1,2}:[0-9]{1,2}"
                r"(?:\.[0-9]+)?(?:[ \t]*(?:Z|[-+][012]?[0-9](?::[0-9]{2})?))?)?"
            ),
        )
    )
)


def vendor_scalar_nodes(root: Node | None) -> Iterator[tuple[int, str, ScalarNode]]:
    """Yield only vendor SHA/branch nodes, including resolved branch aliases.

    Args:
        root: Composed manifest or legacy registry.

    Yields:
        Vendor index, field name and scalar source node.
    """
    if not isinstance(root, MappingNode):
        return
    for key, vendors in root.value:
        if key.value != "vendors" or not isinstance(vendors, SequenceNode):
            continue
        for index, vendor in enumerate(vendors.value):
            if isinstance(vendor, MappingNode):
                for field, node in vendor.value:
                    if (
                        isinstance(field, ScalarNode)
                        and field.value in {"sha", "branch"}
                        and isinstance(node, ScalarNode)
                    ):
                        yield index, field.value, node


def _scalar_tokens(text: str) -> dict[int, tuple[ScalarToken, int]]:
    """Locate scalar tokens and prefixes, including the source of branch aliases.

    Args:
        text: Unmodified YAML source.

    Returns:
        Scalar end offset to token and preceding structural token's end offset.
    """
    result = {}
    previous_end = 0
    for token in yaml.scan(text):
        if isinstance(token, ScalarToken):
            result[token.end_mark.index] = (token, previous_end)
        if not isinstance(token, (AnchorToken, TagToken)):
            previous_end = token.end_mark.index
    return result


def ambiguous_vendor_scalars(
    *,
    text: str,
    root: Node | None,
    tokens: dict[int, tuple[ScalarToken, int]] | None = None,
) -> Iterator[tuple[int, str, ScalarNode]]:
    """Find unquoted string values read differently by the two loaders.

    Explicit string tags and block/quoted strings retain their existing rules.
    PyYAML already rejects non-string values through the manifest schema.

    Args:
        text: Original YAML source.
        root: Composed source tree retaining scalar identity and locations.
        tokens: Already scanned source tokens, when called by the writer.

    Yields:
        Vendor index, field name and ambiguous scalar source node.
    """
    events = list(yaml.parse(text))
    version = next(
        (event.version for event in events if isinstance(event, DocumentStartEvent)),
        None,
    )
    resolver = _YAML11 if version == (1, 1) else _CORE
    scalars = {
        event.start_mark.index: event
        for event in events
        if isinstance(event, ScalarEvent) and event.start_mark is not None
    }
    sources = tokens if tokens is not None else _scalar_tokens(text)
    for index, field, node in vendor_scalar_nodes(root):
        event = scalars.get(node.start_mark.index)
        if (
            node.tag != "tag:yaml.org,2002:str"
            or node.style is not None
            or event is None
            or event.tag is not None
        ):
            continue
        source = sources.get(node.end_mark.index)
        if source is None:
            continue  # Empty/non-string scalars remain the schema's responsibility.
        # PyYAML treats NEL/LS/PS as line breaks, including immediately before
        # or after a scalar token. YAML 1.2 includes them in the scalar instead.
        prefix = text[source[1] : node.start_mark.index]
        suffix = re.match(r"[ \t\x85\u2028\u2029]*", text[node.end_mark.index :])
        surrounding = prefix + (suffix.group() if suffix else "")
        raw = surrounding + text[node.start_mark.index : node.end_mark.index]
        if resolver.fullmatch(node.value) or any(
            char in raw for char in "\x85\u2028\u2029"
        ):
            yield index, field, node


def quote_vendor_scalars(*, text: str, data: object) -> str:
    """Quote ambiguous vendor fields without changing their semantic strings.

    Args:
        text: Newly rendered or losslessly patched manifest/legacy YAML.
        data: Authoritative values before YAML emission can fold Unicode breaks.

    Returns:
        Source with only ambiguous SHA/branch tokens quoted, retaining anchors.

    Raises:
        ValueError: If a lossless edit produced invalid YAML, including aliases.
    """
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid rendered YAML: {error}") from error
    tokens = _scalar_tokens(text)
    ambiguous = list(ambiguous_vendor_scalars(text=text, root=root, tokens=tokens))
    replacements = {
        (
            tokens[node.end_mark.index][0].start_mark.index,
            node.end_mark.index,
        ): json.dumps(node.value)
        for _, _, node in ambiguous
    }
    positions = {node.end_mark.index for _, _, node in ambiguous}
    for _, _, node in vendor_scalar_nodes(root):
        if node.end_mark.index not in positions:
            continue
        token, prefix_start = tokens[node.end_mark.index]
        prefix_end = token.start_mark.index
        trailing = re.match(r"[ \t\x85\u2028\u2029]*", text[node.end_mark.index :])
        suffix_end = node.end_mark.index + (trailing.end() if trailing else 0)
        for start, end in (
            (prefix_start, prefix_end),
            (node.end_mark.index, suffix_end),
        ):
            raw = text[start:end]
            if any(char in raw for char in "\x85\u2028\u2029"):
                replacements[(start, end)] = re.sub(r"[\x85\u2028\u2029]", "\n", raw)
    # PyYAML may emit NEL/LS/PS literally even in quoted strings. Renovate does
    # not fold these YAML 1.1 line breaks. Escape only these vendor field tokens,
    # using the original requested value rather than the already-folded node.
    vendors = data.get("vendors") if isinstance(data, dict) else None
    if isinstance(vendors, list):
        for index, field, node in vendor_scalar_nodes(root):
            vendor = vendors[index]
            value = vendor.get(field) if isinstance(vendor, dict) else None
            if isinstance(value, str) and any(c in value for c in "\x85\u2028\u2029"):
                token = tokens[node.end_mark.index][0]
                suffix = ""
                if token.style in {"|", ">"}:
                    raw = text[token.start_mark.index : token.end_mark.index]
                    suffix = raw[len(raw.rstrip()) :]
                replacements[(token.start_mark.index, token.end_mark.index)] = (
                    json.dumps(value) + suffix
                )
    for (start, end), quoted in sorted(replacements.items(), reverse=True):
        text = text[:start] + quoted + text[end:]
    return text
