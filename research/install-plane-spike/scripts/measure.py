#!/usr/bin/env python3
"""Collect per-target, per-variant scenario evidence, never synthesizing a pass."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common import command, run_payload, target, write_json
from offline import measure_offline
from quarantine import measure_quarantine
from registry import measure_registry


def main() -> None:
    """Collect measurements; scenario failures are evidence, not collection errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--offline-only", action="store_true")
    args = parser.parse_args()
    build = args.build.resolve()
    records: list[dict[str, Any]] = []
    head = command(argv=["git", "rev-parse", "HEAD"], records=records)
    status = command(argv=["git", "status", "--porcelain"], records=records)
    metadata = {
        "schema": 1,
        "target": target(),
        "platform": platform.platform(),
        "collected_utc": datetime.now(UTC).isoformat(),
        "source_head": head["stdout"].strip(),
        "source_status": status["stdout"],
        "metadata_commands": records,
        "workflow_run": (
            f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/"
            f"{os.environ['GITHUB_RUN_ID']}"
            if os.environ.get("GITHUB_RUN_ID")
            else None
        ),
        "note": "pass means only the stated observation; unverified is not a pass",
    }
    with tempfile.TemporaryDirectory(prefix="spike-measure-") as temporary:
        work = Path(temporary)
        offline_work = work / "offline"
        offline_work.mkdir()
        offline = measure_offline(
            build=build, work=offline_work, harden_block=args.offline_only
        )
        registry_work = work / "registry"
        registry_work.mkdir()
        registry = (
            {}
            if args.offline_only
            else measure_registry(build=build, work=registry_work)
        )
        for variant in ("ts", "py"):
            evidence = {**metadata, "variant": variant, "offline": offline[variant]}
            with (build / f"{variant}.tgz").open("rb") as archive:
                evidence["archive_sha256"] = hashlib.file_digest(
                    archive,
                    "sha256",
                ).hexdigest()
            if not args.offline_only:
                root = build / variant
                entries: list[dict[str, Any]] = []
                cold = [
                    run_payload(
                        root=root,
                        variant=variant,
                        home=work / f"{variant}-cold-{number}",
                        records=entries,
                    )
                    for number in range(3)
                ]
                files = [path for path in root.rglob("*") if path.is_file()]
                evidence["no_node"] = {
                    "status": (
                        "pass"
                        if all(item["status"] == "pass" for item in cold)
                        else "fail"
                    ),
                    "PATH": "",
                    "processes": cold,
                    "commands": entries,
                    "scope": "Node/Bun absent from PATH; not physically uninstalled",
                }
                evidence["footprint"] = {
                    "payload_bytes": sum(path.stat().st_size for path in files),
                    "files": len(files),
                    "archive_bytes": (build / f"{variant}.tgz").stat().st_size,
                    "fresh_process_seconds": [item["seconds"] for item in cold],
                    "disk_cold": "unverified: OS page cache not flushed",
                }
                quarantine_root = work / f"quarantine-{variant}"
                shutil.copytree(src=root, dst=quarantine_root)
                evidence["quarantine"] = measure_quarantine(
                    root=quarantine_root,
                    variant=variant,
                    home=work / f"quarantine-home-{variant}",
                )
                evidence["private_registry"] = registry[variant]
                evidence["registry_server"] = registry.get("server", [])
            suffix = "-offline" if args.offline_only else ""
            write_json(
                path=args.results / f"{target()}-{variant}{suffix}.json", value=evidence
            )


if __name__ == "__main__":
    main()
