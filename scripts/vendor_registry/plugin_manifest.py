"""Generated host-adapter manifests for one baked vendor plugin."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from vendor_registry.vendor import Vendor
from vendor_registry.vendor_plugin import VendorPlugin

GENERATED_NOTICE = "do not edit — regenerate via scripts/bake_vendor_plugins.py"
MARKETPLACE_NAME = "ai-skills-vendors"
MARKETPLACE_OWNER = "lgtm-hq"


def render_json(*, payload: dict[str, Any]) -> str:
    """Serialize a mapping as JSON with a stable trailing newline.

    Args:
        payload: JSON-serializable mapping.

    Returns:
        UTF-8 JSON text ending with a newline.
    """
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def plugin_description(*, plugin: VendorPlugin, vendor: Vendor) -> str:
    """Return the description stamped onto per-plugin host manifests.

    Args:
        plugin: Registry plugin slice.
        vendor: Vendor that owns the slice.

    Returns:
        Description including the bake provenance suffix.
    """
    return f"{plugin.description} [baked from vendor '{vendor.id}']"


def plugin_manifest_files(
    *,
    plugin: VendorPlugin,
    vendor: Vendor,
    version: str,
) -> dict[str, str]:
    """Return relative path → JSON text for the four host manifests.

    Args:
        plugin: Registry plugin slice.
        vendor: Vendor that owns the slice.
        version: Pin-derived plugin version.

    Returns:
        POSIX relative paths mapped to pretty JSON.
    """
    author = {"name": vendor.repo.split("/", maxsplit=1)[0]}
    base = {
        "name": plugin.id,
        "version": version,
        "description": plugin_description(plugin=plugin, vendor=vendor),
        "author": author,
    }
    return {
        "plugin.json": render_json(payload={**base, "skills": "./skills/"}),
        ".claude-plugin/plugin.json": render_json(payload=base),
        ".codex-plugin/plugin.json": render_json(payload=base),
        ".cursor-plugin/plugin.json": render_json(
            payload={
                **base,
                "displayName": plugin.id,
                "license": vendor.license,
                "skills": "./skills/",
            },
        ),
    }


def write_plugin_manifests(
    *,
    destination: Path,
    plugin: VendorPlugin,
    vendor: Vendor,
    version: str,
) -> None:
    """Write the four host-adapter manifests for one baked plugin.

    Claude, Cursor, Codex, and root Agent Plugins manifests are generated
    adapters (ADR-0002). Hosts ignore foreign manifest dirs.

    Args:
        destination: Baked plugin directory.
        plugin: Registry plugin slice.
        vendor: Vendor that owns the slice.
        version: Pin-derived plugin version.
    """
    for relative, text in plugin_manifest_files(
        plugin=plugin,
        vendor=vendor,
        version=version,
    ).items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def render_marketplace(*, plugins: list[dict[str, str]]) -> str:
    """Render the baked-output Claude marketplace JSON.

    Args:
        plugins: Marketplace plugin entries in bake order.

    Returns:
        Pretty JSON text with a trailing newline.
    """
    return render_json(
        payload={
            "name": MARKETPLACE_NAME,
            "owner": {"name": MARKETPLACE_OWNER},
            "$generated": GENERATED_NOTICE,
            "plugins": plugins,
        },
    )


def render_bake_manifest(
    *,
    vendors: tuple[Vendor, ...],
    coverage: str,
    files: dict[str, str],
) -> str:
    """Render the bake lock that ``--check`` compares to ``vendors.yaml``.

    The lock records the plugin-relevant registry slice, a digest of
    ``COVERAGE.md``, and a path→digest map of every generated file except
    the lock itself so truncated, modified, or extra bake output fails.

    Args:
        vendors: Registry vendors in source order.
        coverage: Coverage report text whose digest is stored.
        files: POSIX relative path → SHA-256 hex digest.

    Returns:
        Pretty JSON text with a trailing newline.
    """
    return render_json(
        payload={
            "$generated": GENERATED_NOTICE,
            "coverageSha256": hashlib.sha256(
                coverage.encode(encoding="utf-8"),
            ).hexdigest(),
            "vendors": [_bake_lock_vendor(vendor=vendor) for vendor in vendors],
            "files": files,
        },
    )


def _bake_lock_vendor(*, vendor: Vendor) -> dict[str, object]:
    """Serialize one vendor's pin and plugin slice for the bake lock.

    Args:
        vendor: Registry vendor.

    Returns:
        JSON-serializable vendor lock object.
    """
    return {
        "id": vendor.id,
        "sha": vendor.sha,
        "displayRef": vendor.display_ref,
        "plugins": [_bake_lock_plugin(plugin=plugin) for plugin in vendor.plugins],
    }


def _bake_lock_plugin(*, plugin: VendorPlugin) -> dict[str, object]:
    """Serialize one plugin declaration for the bake lock.

    Args:
        plugin: Registry plugin slice.

    Returns:
        JSON-serializable plugin lock object.
    """
    skills: str | list[str]
    if plugin.skills == "*":
        skills = "*"
    else:
        skills = list(plugin.skills)
    return {
        "id": plugin.id,
        "description": plugin.description,
        "skillsRoot": plugin.skills_root,
        "skills": skills,
        "extraSkills": list(plugin.extra_skills),
        "renameSkills": dict(plugin.rename_skills),
        "agents": list(plugin.agents),
    }
