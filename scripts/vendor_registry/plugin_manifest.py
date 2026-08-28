"""Generated host-adapter manifests for one baked vendor plugin."""

from __future__ import annotations

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
    author = {"name": vendor.repo.split("/", maxsplit=1)[0]}
    base = {
        "name": plugin.id,
        "version": version,
        "description": plugin_description(plugin=plugin, vendor=vendor),
        "author": author,
    }
    claude_dir = destination / ".claude-plugin"
    cursor_dir = destination / ".cursor-plugin"
    codex_dir = destination / ".codex-plugin"
    claude_dir.mkdir(parents=True, exist_ok=True)
    cursor_dir.mkdir(parents=True, exist_ok=True)
    codex_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "plugin.json").write_text(
        render_json(payload=base),
        encoding="utf-8",
    )
    (codex_dir / "plugin.json").write_text(
        render_json(payload=base),
        encoding="utf-8",
    )
    (cursor_dir / "plugin.json").write_text(
        render_json(
            payload={
                **base,
                "displayName": plugin.id,
                "license": vendor.license,
                "skills": "./skills/",
            },
        ),
        encoding="utf-8",
    )
    (destination / "plugin.json").write_text(
        render_json(payload={**base, "skills": "./skills/"}),
        encoding="utf-8",
    )


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
