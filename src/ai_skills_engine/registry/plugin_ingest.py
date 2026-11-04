"""Bake and offline-check ingestion observations derived from actual files."""

import stat
from itertools import chain
from pathlib import Path

from ai_skills_engine.registry.ingest_checks import (
    RULESET_VERSION,
    limits_record,
    safe_diagnostic,
    scan_paths,
    validate_input_tree,
)
from ai_skills_engine.registry.safe_tree import walk_directories, walk_files
from ai_skills_engine.registry.vendor import Vendor
from ai_skills_engine.registry.vendor_plugin import VendorPlugin


def scan_plugin(
    *, root: Path, vendor: Vendor, plugin: VendorPlugin
) -> list[dict[str, object]]:
    """Rescan canonical plugin-relative files using only registry-owned policy.

    Paths and digests acknowledge the bytes actually published, after skill-name
    rewriting. The lock cannot grant an acknowledgement or change a limit.

    Args:
        root: Staged or existing baked plugin directory.
        vendor: Consumer-owned policy.
        plugin: Plugin identity for finding context.

    Returns:
        Acknowledged findings with plugin identity.

    Raises:
        ValueError: On any unsafe content, limit or noncanonical file mode.
    """
    from ai_skills_engine.registry.ingest_checks import normalized_mode

    validate_input_tree(root=root, vendor=vendor.id, limits=vendor.ingest_limits)
    for directory in chain((root,), walk_directories(root=root)):
        normalized_mode(
            mode=directory.stat().st_mode,
            vendor=vendor.id,
            path=directory.relative_to(root).as_posix(),
        )
    paths = []
    for path in walk_files(root=root):
        relative = path.relative_to(root).as_posix()
        mode = stat.S_IMODE(path.stat().st_mode)
        expected = normalized_mode(mode=mode, vendor=vendor.id, path=relative)
        if mode != expected:
            raise ValueError(
                safe_diagnostic(
                    f"vendor {vendor.id}: {relative}: noncanonical file mode"
                )
            )
        paths.append((path, relative))
    return [
        {"plugin": plugin.id, **finding}
        for finding in scan_paths(
            paths=paths,
            vendor=vendor.id,
            limits=vendor.ingest_limits,
            allow=vendor.ingest_allow,
        )
    ]


def ingest_record(
    *, vendors: tuple[Vendor, ...], baked_root: Path
) -> dict[str, object]:
    """Build fresh audit metadata, never accepting lock-supplied decisions.

    Args:
        vendors: Authoritative registry entries.
        baked_root: Generated plugin directory.

    Returns:
        Version, effective limits and acknowledged findings by vendor.
    """
    return {
        "ruleSetVersion": RULESET_VERSION,
        "vendors": {
            vendor.id: {
                "limits": limits_record(vendor.ingest_limits),
                "acknowledgedFindings": [
                    finding
                    for plugin in vendor.plugins
                    for finding in scan_plugin(
                        root=baked_root / plugin.id, vendor=vendor, plugin=plugin
                    )
                ],
            }
            for vendor in vendors
            if vendor.plugins
        },
    }
