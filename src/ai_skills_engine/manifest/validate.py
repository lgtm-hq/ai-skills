"""JSON Schema structural validation followed by identity/selection checks."""

import json
from collections.abc import Mapping

# nosemgrep: python37-compatibility-importlib2 - pyproject.toml requires Python >=3.13
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.identity import parse_id


def validate_inventory(
    root: Path,
    *,
    vendor_roots: Mapping[str, Path] | None = None,
) -> tuple[Diagnostic, ...]:
    """Validate payloads and explicit edges using the production offline loader.

    Args:
        root: Consumer repository root.
        vendor_roots: Explicit offline vendor snapshots.

    Returns:
        Inventory diagnostics, preserving warning/error severities.
    """
    from ai_skills_engine.inventory.load import load_inventory

    return load_inventory(root, vendor_roots=vendor_roots).diagnostics


def schema_path() -> resources.abc.Traversable:
    """Locate the v1 schema resource shipped with this engine.

    Returns:
        Read-only packaged JSON Schema resource.
    """
    return resources.files("ai_skills_engine.manifest").joinpath(
        "ai-skills.v1.schema.json"
    )


def validate_document(
    data: object,
    *,
    imported_packages: Mapping[str, set[str]] | None = None,
) -> list[Diagnostic]:
    """Validate structure, unique identities, selectors and explicit exports.

    Args:
        data: Duplicate-key-checked YAML document.
        imported_packages: Consumer vendor alias to qualified packages from an
            explicitly loaded local vendor manifest.

    Returns:
        Ordered errors with codes, JSON pointers and actionable messages.
    """
    try:
        normalized = json.loads(json.dumps(data, allow_nan=False))
    except (TypeError, ValueError, RecursionError) as error:
        return [
            Diagnostic("schema", "/", f"Manifest must contain JSON values: {error}")
        ]
    if normalized != data:
        return [Diagnostic("schema", "/", "Manifest mapping keys must be strings")]
    schema = json.loads(schema_path().read_text(encoding="utf-8"))
    findings = [
        Diagnostic(
            "schema",
            "/" + "/".join(str(part) for part in error.absolute_path),
            error.message,
        )
        for error in Draft202012Validator(schema).iter_errors(data)
    ]
    if findings:
        return findings
    return _semantic(data=data, imported_packages=imported_packages or {})


def _semantic(
    *, data: Any, imported_packages: Mapping[str, set[str]]
) -> list[Diagnostic]:
    """Check cross-field v1 contracts after the structural pass.

    Args:
        data: Structurally validated document.
        imported_packages: Known offline vendor package identities.

    Returns:
        Semantic diagnostics.
    """
    findings: list[Diagnostic] = []
    publisher = data["publisher"]["id"]
    seen: set[str] = set()
    packages: set[str] = set()

    def identity(value: str, location: str) -> None:
        """Register one unique qualified identity."""
        if value in seen:
            findings.append(
                Diagnostic("duplicate-id", location, f"Duplicate identity: {value}")
            )
        seen.add(value)
        try:
            parse_id(value)
        except ValueError as error:
            findings.append(Diagnostic("invalid-id", location, str(error)))

    for index, package in enumerate(data.get("packages", [])):
        qualified = f"{publisher}/{package['id']}"
        packages.add(qualified)
        identity(qualified, f"/packages/{index}/id")
        for offset, capability in enumerate(package.get("capabilities", [])):
            name = capability["id"]
            identity(
                f"{qualified}:{capability.get('role', 'skill')}/{name}",
                f"/packages/{index}/capabilities/{offset}",
            )
        for offset, resource in enumerate(package.get("resources", [])):
            identity(
                f"{qualified}:resource/{resource['id']}",
                f"/packages/{index}/resources/{offset}",
            )
    aliases: set[str] = set()
    for index, vendor in enumerate(data.get("vendors", [])):
        if vendor["id"] in aliases:
            findings.append(
                Diagnostic(
                    "duplicate-id",
                    f"/vendors/{index}/id",
                    f"Duplicate vendor alias: {vendor['id']}",
                )
            )
        aliases.add(vendor["id"])
        if vendor["id"] in imported_packages:
            packages.update(imported_packages[vendor["id"]])
            if "mapping" in vendor:
                findings.append(
                    Diagnostic(
                        "mapping-on-manifest-vendor",
                        f"/vendors/{index}/mapping",
                        "A manifest vendor cannot have consumer mapping",
                    )
                )
        for offset, package in enumerate(vendor.get("mapping", {}).get("packages", [])):
            qualified = f"{vendor['id']}/{package['id']}"
            packages.add(qualified)
            identity(qualified, f"/vendors/{index}/mapping/packages/{offset}/id")
            for name, capability in package.get("capabilities", {}).items():
                identity(
                    f"{qualified}:skill/{capability.get('id', name)}",
                    f"/vendors/{index}/mapping/packages/{offset}/capabilities/{name}",
                )

    def walk(value: Any, location: str = "") -> None:
        """Inspect selector-bearing fields without entering opaque extensions."""
        if isinstance(value, dict):
            for key, item in value.items():
                if key.startswith("x-"):
                    continue
                target = f"{location}/{key}"
                if key in {
                    "requires",
                    "related",
                    "resources",
                    "include",
                    "exclude",
                    "exports",
                } and isinstance(item, list):
                    for index, selector in enumerate(item):
                        if not isinstance(selector, str):
                            continue
                        resolved = (
                            f"{publisher}/{selector}"
                            if key == "exports" and "/" not in selector
                            else selector
                        )
                        try:
                            parse_id(resolved, selector=key != "exports")
                        except ValueError as error:
                            findings.append(
                                Diagnostic(
                                    "invalid-selector", f"{target}/{index}", str(error)
                                )
                            )
                            continue
                        if key == "exports" and resolved not in packages:
                            findings.append(
                                Diagnostic(
                                    "dangling-export",
                                    f"{target}/{index}",
                                    "Export is not a local or imported package: "
                                    f"{selector}",
                                )
                            )
                walk(item, target)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{location}/{index}")

    walk(data)
    for category, keys in {
        "migrations": ("from", "to"),
        "attestations": ("capability",),
        "collisions": ("capability",),
    }.items():
        for index, override in enumerate(data.get("overrides", {}).get(category, [])):
            for key in keys:
                try:
                    parse_id(override[key])
                except ValueError as error:
                    findings.append(
                        Diagnostic(
                            "invalid-id",
                            f"/overrides/{category}/{index}/{key}",
                            str(error),
                        ),
                    )
    return findings
