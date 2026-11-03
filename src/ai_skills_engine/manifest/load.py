"""Duplicate-key-safe loading and the offline vendor authority boundary."""

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import yaml
from yaml.tokens import ScalarToken

from ai_skills_engine.manifest.codec import decode
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.model import Manifest
from ai_skills_engine.registry.registry import load_unique_yaml_text


def _publication_packages(document: dict[str, Any]) -> set[str]:
    """Read publication package names without importing vendor authority.

    Args:
        document: Structurally validated vendor manifest.

    Returns:
        Own packages and explicitly qualified re-exports.
    """
    return {
        f"{document['publisher']['id']}/{item['id']}"
        for item in document.get("packages", [])
    } | {value for value in document.get("exports", []) if "/" in value}


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
    ignore_authority: bool = False,
) -> tuple[Manifest, Mapping[str, Manifest], tuple[Diagnostic, ...]]:
    """Validate consumer and explicitly supplied offline vendor declarations.

    Vendor policy, overrides and extensions are diagnostic-only and are removed
    from imported models. Nothing is merged into the consumer's policy. Roots
    are explicit local inputs; loading never fetches or executes vendor content.

    Args:
        path: Consumer declaration.
        vendor_roots: Consumer vendor ID to locally available repository root.
        ignore_authority: Strip current publisher authority during recursive imports.

    Returns:
        Consumer, sanitized imports keyed by consumer alias, and diagnostics.

    Raises:
        ValueError: If consumer or vendor validation fails.
    """
    from ai_skills_engine.manifest.validate import validate_document

    data = read_document(path)
    if ignore_authority:
        data = {
            key: value
            for key, value in data.items()
            if key not in {"policy", "overrides"} and not key.startswith("x-")
        }
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
        nested_packages: dict[str, set[str]] = {}
        for nested in document.get("vendors", []):
            nested_root = (vendor_roots or {}).get(alias + "/" + nested["id"])
            if nested_root and (nested_root / "ai-skills.yaml").is_file():
                from ai_skills_engine.inventory.payload import source_path

                source_path(root=nested_root, relative="ai-skills.yaml")
                nested_document = read_document(nested_root / "ai-skills.yaml")
                nested_document = {
                    key: value
                    for key, value in nested_document.items()
                    if key not in {"policy", "overrides"} and not key.startswith("x-")
                }
                if any(
                    item.code == "schema" for item in validate_document(nested_document)
                ):
                    raise ValueError(f"Invalid nested vendor manifest {nested['id']}")
                nested_packages[nested["id"]] = _publication_packages(nested_document)
        findings = validate_document(document, imported_packages=nested_packages)
        if document.get("vendors"):
            # Recursive inventory validates re-exports against the actual pins.
            # Offline missing nested inputs must retain provenance diagnostics.
            diagnostics.extend(
                item for item in findings if item.code == "dangling-export"
            )
            findings = [item for item in findings if item.code != "dangling-export"]
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
                    *[
                        f"{manifest.publisher.id}/{package.id}"
                        for package in manifest.packages
                    ],
                    *[value for value in manifest.exports if "/" in value],
                }
                for alias, manifest in imported.items()
            },
        )
    )
    return cast(Manifest, decode(data, Manifest)), imported, tuple(diagnostics)
