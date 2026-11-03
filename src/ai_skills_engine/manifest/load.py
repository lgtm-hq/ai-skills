"""Duplicate-key-safe loading and the offline vendor authority boundary."""

import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from yaml.tokens import ScalarToken

from ai_skills_engine.manifest.codec import decode
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.model import Manifest
from ai_skills_engine.registry.registry import load_unique_yaml_text


def _check_sha_sources(*, text: str, path: Path) -> None:
    """Check SHA source bytes before YAML decoding erases escapes and aliases.

    Args:
        text: Unmodified YAML source.
        path: Source path for actionable errors.

    Raises:
        ValueError: If a vendor SHA is not a directly replaceable scalar.
    """
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML in {path}: {error}") from error

    def fields(node: Node | None) -> dict[str, Node]:
        """Read structural keys without constructing values or interpreting tags."""
        if not isinstance(node, MappingNode):
            return {}
        return {
            key.value: value for key, value in node.value if isinstance(key, ScalarNode)
        }

    vendors = fields(root).get("vendors")
    if not isinstance(vendors, SequenceNode):
        return
    for index, vendor in enumerate(vendors.value):
        record = fields(vendor)
        sha = record.get("sha")
        if sha is None:
            continue  # The schema owns required fields and other structure.
        raw = text[sha.start_mark.index : sha.end_mark.index]
        if re.fullmatch(r"[0-9a-f]{40}|'[0-9a-f]{40}'|\"[0-9a-f]{40}\"", raw):
            continue
        identity = record.get("id")
        alias = identity.value if isinstance(identity, ScalarNode) else "unknown"
        raise ValueError(
            f"{path}: schema /vendors/{index}/sha (vendor {alias}): SHA must be a "
            "direct, unescaped 40-hex scalar, plain or ordinary single/double "
            "quoted; no escape sequences, folded/block scalars, anchors, aliases "
            "or tags (required for native Renovate SHA updates)"
        )


def read_document(path: Path) -> dict[str, Any]:
    """Load a manifest mapping using the existing duplicate-key-safe loader.

    Args:
        path: Manifest path; no vendor code is imported or executed.

    Returns:
        Parsed mapping.

    Raises:
        ValueError: On malformed YAML, duplicate keys or a non-mapping root.
    """
    text = path.read_text(encoding="utf-8")
    _check_sha_sources(text=text, path=path)
    data = load_unique_yaml_text(text=text, source=str(path))
    # PyYAML accepts an unseparated comment after a quoted scalar. Enforce
    # YAML's lexical boundary here before validation or compatibility publication.
    for token in yaml.scan(text):
        if (
            isinstance(token, ScalarToken)
            and token.style in {"'", '"'}
            and text[token.end_mark.index : token.end_mark.index + 1] == "#"
        ):
            raise ValueError(
                f"{path}: comments after quoted scalars require whitespace "
                f"at line {token.end_mark.line + 1}"
            )
    if not isinstance(data, dict):
        raise TypeError(f"{path}: manifest must be a mapping")
    return cast(dict[str, Any], data)


def load_manifest(path: Path) -> Manifest:
    """Validate a declaration before creating its frozen typed model.

    Args:
        path: Local manifest file.

    Returns:
        Validated manifest.

    Raises:
        ValueError: On structural or semantic diagnostics.
    """
    from ai_skills_engine.manifest.validate import validate_document

    data = read_document(path)
    errors = validate_document(data)
    if errors:
        raise ValueError(
            "\n".join(f"{item.code} {item.location}: {item.message}" for item in errors)
        )
    return cast(Manifest, decode(data, Manifest))


def load_consumer(
    path: Path,
    *,
    vendor_roots: Mapping[str, Path] | None = None,
) -> tuple[Manifest, Mapping[str, Manifest], tuple[Diagnostic, ...]]:
    """Validate consumer and explicitly supplied offline vendor declarations.

    Vendor policy, overrides and extensions are diagnostic-only and are removed
    from imported models. Nothing is merged into the consumer's policy. Roots
    are explicit local inputs; loading never fetches or executes vendor content.

    Args:
        path: Consumer declaration.
        vendor_roots: Consumer vendor ID to locally available repository root.

    Returns:
        Consumer, sanitized imports keyed by consumer alias, and diagnostics.

    Raises:
        ValueError: If consumer or vendor validation fails.
    """
    from ai_skills_engine.manifest.validate import validate_document

    data = read_document(path)
    structural = [item for item in validate_document(data) if item.code == "schema"]
    if structural:
        raise ValueError(str(structural))
    imported: dict[str, Manifest] = {}
    diagnostics: list[Diagnostic] = []
    for vendor in data.get("vendors", []):
        alias = vendor["id"]
        root = (vendor_roots or {}).get(alias)
        if root is None or not (root / "ai-skills.yaml").is_file():
            continue
        document = read_document(root / "ai-skills.yaml")
        for key in tuple(document):
            if key in {"policy", "overrides"} or key.startswith("x-"):
                diagnostics.append(
                    Diagnostic(
                        "vendor-authority-ignored",
                        f"/vendors/{alias}/{key}",
                        "Vendor policy and trust-related declarations "
                        "are ignored by the consumer",
                        warning=True,
                    )
                )
                document.pop(key)
        findings = validate_document(document)
        if findings:
            raise ValueError(f"Invalid vendor manifest {alias}: {findings}")
        imported[alias] = replace(
            cast(Manifest, decode(document, Manifest)),
            policy=None,
            overrides=None,
        )
    diagnostics.extend(
        validate_document(
            data,
            imported_packages={
                alias: {
                    f"{manifest.publisher.id}/{package.id}"
                    for package in manifest.packages
                }
                for alias, manifest in imported.items()
            },
        )
    )
    return cast(Manifest, decode(data, Manifest)), imported, tuple(diagnostics)
