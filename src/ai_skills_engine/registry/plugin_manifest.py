"""Generated host-adapter manifests for one baked vendor plugin."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ai_skills_engine.envelopes import (
    ALL_HOSTS,
    PackageEnvelope,
    plugin_envelopes,
    write_files,
)
from ai_skills_engine.registry.vendor import Vendor
from ai_skills_engine.registry.vendor_plugin import VendorPlugin

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
    return baked_description(description=plugin.description, vendor_id=vendor.id)


def baked_description(*, description: str, vendor_id: str) -> str:
    """Append the bake provenance suffix to a vendor package description.

    Args:
        description: Declared package description.
        vendor_id: Vendor that owns the package.

    Returns:
        Description stamped onto per-plugin host manifests.
    """
    return f"{description} [baked from vendor '{vendor_id}']"


def vendor_envelope(*, plugin: VendorPlugin, vendor: Vendor) -> PackageEnvelope:
    """Return the envelope presentation for one baked vendor plugin.

    Args:
        plugin: Registry plugin slice.
        vendor: Vendor that owns the slice.

    Returns:
        Presentation consumed by the shared envelope generator.
    """
    return PackageEnvelope(
        package=f"{vendor.id}/{plugin.id}",
        plugin=plugin.id,
        display_name=plugin.id,
        description=plugin.description,
        plugin_description=plugin_description(plugin=plugin, vendor=vendor),
        author=vendor.repo.split("/", maxsplit=1)[0],
        license=vendor.license,
    )


def _baked_roles(
    *, plugin: VendorPlugin, vendor: Vendor
) -> tuple[tuple[str, str], ...]:
    """Return the roles a baked plugin tree delivers.

    Args:
        plugin: Registry plugin slice.
        vendor: Vendor that owns the slice.

    Returns:
        ``(capability ID, role)`` pairs; skills always ship a ``skills/`` tree.
    """
    package = f"{vendor.id}/{plugin.id}"
    return (
        (f"{package}:skill/skills", "skill"),
        *((f"{package}:specialist/{agent}", "specialist") for agent in plugin.agents),
    )


def plugin_manifest_bytes(
    *,
    plugin: VendorPlugin,
    vendor: Vendor,
    version: str,
) -> dict[str, bytes]:
    """Return relative path → bytes for the generated host envelopes.

    Args:
        plugin: Registry plugin slice.
        vendor: Vendor that owns the slice.
        version: Pin-derived plugin version.

    Returns:
        POSIX relative paths mapped to exact envelope bytes.
    """
    return plugin_envelopes(
        package=vendor_envelope(plugin=plugin, vendor=vendor),
        version=version,
        roles=_baked_roles(plugin=plugin, vendor=vendor),
        hosts=ALL_HOSTS,
    )


def write_plugin_manifests(
    *,
    destination: Path,
    plugin: VendorPlugin,
    vendor: Vendor,
    version: str,
) -> None:
    """Write the four host-adapter manifests for one baked plugin.

    Claude, Cursor, Codex, and root Agent Plugins manifests are generated
    adapters (ADR-0002) produced by the shared envelope generator.

    Args:
        destination: Baked plugin directory.
        plugin: Registry plugin slice.
        vendor: Vendor that owns the slice.
        version: Pin-derived plugin version.
    """
    write_files(
        destination=destination,
        files=plugin_manifest_bytes(plugin=plugin, vendor=vendor, version=version),
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


def render_bake_manifest(
    *,
    vendors: tuple[Vendor, ...],
    coverage: str,
    files: dict[str, str],
    coverage_inputs: dict[str, object],
    ingest_checks: dict[str, object],
) -> str:
    """Render the bake lock that ``--check`` compares to ``vendors.yaml``.

    The lock records the plugin-relevant registry slice, coverage renderer
    inputs, and a path→digest map of every generated file except the lock
    itself. ``--check`` allowlists lock keys, re-derives ingested counts,
    explode names, and collisions from the baked tree, and re-renders
    ``COVERAGE.md`` from those disk-derived inputs plus bake-time skipped
    paths. A coverage report cannot be forged by editing only the lock.

    Args:
        vendors: Registry vendors in source order.
        coverage: Coverage report text whose digest is stored.
        files: POSIX relative path → SHA-256 hex digest.
        coverage_inputs: Renderer inputs recorded at bake time.
        ingest_checks: Fresh content scan observations and effective limits.

    Returns:
        Pretty JSON text with a trailing newline.
    """
    return render_json(
        payload={
            "$generated": GENERATED_NOTICE,
            "coverageSha256": hashlib.sha256(
                coverage.encode(encoding="utf-8"),
            ).hexdigest(),
            "coverageInputs": coverage_inputs,
            "ingestChecks": ingest_checks,
            "vendors": bake_lock_vendors(vendors=vendors),
            "files": files,
        },
    )


def bake_lock_vendors(*, vendors: tuple[Vendor, ...]) -> list[dict[str, object]]:
    """Serialize registry vendors for the bake lock.

    Args:
        vendors: Registry vendors in source order.

    Returns:
        JSON-serializable vendor lock objects.
    """
    return [_bake_lock_vendor(vendor=vendor) for vendor in vendors]


def _bake_lock_vendor(*, vendor: Vendor) -> dict[str, object]:
    """Serialize one vendor's pin and plugin slice for the bake lock.

    Args:
        vendor: Registry vendor.

    Returns:
        JSON-serializable vendor lock object.
    """
    return {
        "id": vendor.id,
        "repo": vendor.repo,
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
        "extraFiles": list(plugin.extra_files),
        "renameSkills": dict(plugin.rename_skills),
        "agents": list(plugin.agents),
    }
