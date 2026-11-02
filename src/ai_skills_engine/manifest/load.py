"""Duplicate-key-safe loading and the offline vendor authority boundary."""

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from ai_skills_engine.manifest.codec import decode
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.model import Manifest
from ai_skills_engine.registry.registry import load_unique_yaml_text


def read_document(path: Path) -> dict[str, Any]:
    """Load a manifest mapping using the existing duplicate-key-safe loader.

    Args:
        path: Manifest path; no vendor code is imported or executed.

    Returns:
        Parsed mapping.

    Raises:
        ValueError: On malformed YAML, duplicate keys or a non-mapping root.
    """
    data = load_unique_yaml_text(
        text=path.read_text(encoding="utf-8"), source=str(path)
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
