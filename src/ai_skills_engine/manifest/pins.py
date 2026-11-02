"""Authoritative vendor edits retaining consumer-owned declaration fields."""

from pathlib import Path
from typing import Any

from ai_skills_engine.manifest.edit import dump_document, patch_document
from ai_skills_engine.manifest.legacy import LEGACY_PACKAGE_FIELDS, write_legacy
from ai_skills_engine.manifest.load import load_manifest, read_document
from ai_skills_engine.manifest.migrate import vendor_declaration


def write_vendors(path: Path, vendors: list[dict[str, Any]]) -> str:
    """Apply legacy management edits without dropping manifest-only fields.

    Args:
        path: Authoritative manifest.
        vendors: Validated replacement legacy vendor declarations.

    Returns:
        Original manifest text for transactional refresh rollback.

    Raises:
        ValueError: If the resulting manifest or derived registry is invalid.
    """
    original = path.read_text(encoding="utf-8")
    data = read_document(path)
    existing = {vendor["id"]: vendor for vendor in data.get("vendors", [])}
    declarations = []
    for raw in vendors:
        incoming = vendor_declaration(raw)
        previous = existing.get(raw["id"], {})
        mapping = {
            **{
                key: value
                for key, value in previous.get("mapping", {}).items()
                if key not in {"skillRoots", "packages"}
            },
            **incoming["mapping"],
        }
        if "packages" in incoming["mapping"]:
            old_packages = {
                package["id"]: package
                for package in previous.get("mapping", {}).get("packages", [])
            }
            mapping["packages"] = [
                {
                    **{
                        key: value
                        for key, value in old_packages.get(package["id"], {}).items()
                        if key not in LEGACY_PACKAGE_FIELDS
                    },
                    **package,
                }
                for package in incoming["mapping"]["packages"]
            ]
        declarations.append(
            {
                **{
                    key: value
                    for key, value in previous.items()
                    if key not in {"branch", "displayRef", "license", "homepage"}
                },
                **incoming,
                "mapping": mapping,
            }
        )
    structural = any(
        set(previous) != set(replacement)
        for previous, replacement in zip(data.get("vendors", []), declarations)
    ) or len(data.get("vendors", [])) != len(declarations)
    declarations = [
        {
            **{
                key: vendor[key]
                for key in ("id", "repo", "sha", "branch")
                if key in vendor
            },
            **{
                key: value
                for key, value in vendor.items()
                if key not in {"id", "repo", "sha", "branch"}
            },
        }
        for vendor in declarations
    ]
    data["vendors"] = declarations
    path.write_text(
        dump_document(data) if structural else patch_document(text=original, data=data),
        encoding="utf-8",
    )
    try:
        load_manifest(path)
        write_legacy(path.parent)
        from ai_skills_engine.registry.registry import load_registry

        load_registry(registry_path=path.parent / "vendors.yaml")
    except (TypeError, ValueError):
        path.write_text(original, encoding="utf-8")
        write_legacy(path.parent)
        raise
    return original
