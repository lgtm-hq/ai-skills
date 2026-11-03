"""Authoritative vendor edits retaining consumer-owned declaration fields."""

import stat
from pathlib import Path
from typing import Any

from ai_skills_engine.manifest.edit import dump_document, patch_document
from ai_skills_engine.manifest.legacy import LEGACY_PACKAGE_FIELDS, write_legacy
from ai_skills_engine.manifest.load import load_manifest, read_document
from ai_skills_engine.manifest.migrate import vendor_declaration


def _restore_files(
    *, originals: dict[Path, tuple[bytes, int] | None], error: Exception
) -> None:
    """Restore each publication independently, retaining cleanup evidence on failure.

    Args:
        originals: Original bytes and modes, or absence, for every destination.
        error: Original failure to annotate without replacing it.
    """
    for destination, previous in originals.items():
        try:
            if previous is None:
                destination.unlink(missing_ok=True)
            else:
                content, mode = previous
                if not destination.exists() or destination.read_bytes() != content:
                    destination.write_bytes(content)
                if stat.S_IMODE(destination.stat().st_mode) != mode:
                    destination.chmod(mode)
        except OSError as cleanup_error:
            action = (
                "remove the newly created file"
                if previous is None
                else f"restore its original bytes and mode {previous[1]:#o}"
            )
            error.add_note(
                f"Transaction cleanup failed for {destination}: {cleanup_error!r}; "
                f"manually {action} before retrying."
            )


def write_vendors(path: Path, vendors: list[dict[str, Any]]) -> str:
    """Apply legacy management edits without dropping manifest-only fields.

    Args:
        path: Authoritative manifest.
        vendors: Validated replacement legacy vendor declarations.

    Returns:
        Original manifest text for transactional refresh rollback.

    Raises:
        OSError: If publication fails; cleanup failures annotate the original error.
        ValueError: If the resulting manifest or derived registry is invalid.
    """
    original = path.read_bytes().decode("utf-8")
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
    updated = (
        dump_document(data) if structural else patch_document(text=original, data=data)
    )
    originals = {
        destination: (
            (
                destination.read_bytes(),
                stat.S_IMODE(destination.stat().st_mode),
            )
            if destination.exists()
            else None
        )
        for destination in (
            path,
            path.parent / "bundles.yaml",
            path.parent / "vendors.yaml",
        )
    }
    try:
        if updated != original:
            path.write_text(updated, encoding="utf-8")
        load_manifest(path)
        write_legacy(path.parent)
        from ai_skills_engine.registry.registry import load_registry

        load_registry(registry_path=path.parent / "vendors.yaml")
    except (OSError, TypeError, ValueError) as error:
        _restore_files(originals=originals, error=error)
        raise
    return original
