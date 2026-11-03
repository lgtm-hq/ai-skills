"""One-shot migration of this repository's legacy author registries."""

from pathlib import Path
from typing import Any

from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.layout import encode_template
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.validate import validate_document
from ai_skills_engine.registry.registry import load_registry


def vendor_declaration(raw: dict[str, Any]) -> dict[str, Any]:
    """Move all legacy discovery/slice fields into consumer-owned mapping.

    Args:
        raw: Validated legacy vendor, including all optional slice fields.

    Returns:
        Manifest vendor with stable writer ordering for readable diffs.
    """
    return {
        **{
            key: value
            for key, value in raw.items()
            if key not in {"skillRoots", "plugins"}
        },
        "mapping": {
            "skillRoots": raw["skillRoots"],
            **({"packages": raw["plugins"]} if "plugins" in raw else {}),
        },
    }


def migrate(repo_root: Path) -> Path:
    """Create the authoritative manifest without modifying legacy files.

    Args:
        repo_root: Repository containing both legacy registries.

    Returns:
        Newly written manifest path.

    Raises:
        ValueError: If input is invalid or the manifest already exists.
    """
    destination = repo_root / "ai-skills.yaml"
    if destination.exists():
        raise ValueError("ai-skills.yaml already exists; migration is one-shot")
    load_registry(registry_path=repo_root / "vendors.yaml")
    bundles = read_document(repo_root / "bundles.yaml")
    vendors = read_document(repo_root / "vendors.yaml")
    packages: list[dict[str, Any]] = []
    for key, group in bundles["groups"].items():
        package = {
            field: value
            for field, value in group.items()
            if field in {"id", "name", "description"}
        }
        package["capabilities"] = [
            {"id": name, "path": f"skills/{name}"} for name in group["skills"]
        ]
        package["x-legacy-group"] = key
        extras = {
            field: value
            for field, value in group.items()
            if field not in {"id", "name", "description", "skills"}
        }
        if extras:
            package["x-legacy-fields"] = extras
        packages.append(package)
    if "ungrouped" in bundles:
        packages.append(
            {
                "id": "other",
                "capabilities": [
                    {"id": name, "path": f"skills/{name}"}
                    for name in bundles["ungrouped"]
                ],
                "x-legacy-ungrouped": True,
            }
        )
    data = {
        "apiVersion": "ai-skills.dev/v1",
        "publisher": {"id": "lgtm-hq", "repo": "lgtm-hq/ai-skills"},
        "packages": packages,
        "vendors": [vendor_declaration(raw) for raw in vendors["vendors"]],
        "exports": [
            package["id"]
            for package in packages
            if not package.get("x-legacy-ungrouped")
        ]
        + [
            f"{vendor['id']}/{package['id']}"
            for vendor in vendors["vendors"]
            for package in vendor.get("plugins", [])
        ],
        "x-legacy-fields": {
            key: value
            for key, value in bundles.items()
            if key not in {"groups", "ungrouped"}
        },
        "x-legacy-format": {
            name: encode_template((repo_root / name).read_bytes())
            for name in ("bundles.yaml", "vendors.yaml")
        },
    }
    findings = validate_document(data)
    if findings:
        raise ValueError(f"Cannot migrate invalid declarations: {findings}")
    destination.write_text(dump_document(data), encoding="utf-8")
    return destination
