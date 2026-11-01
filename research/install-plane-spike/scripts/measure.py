#!/usr/bin/env python3
"""Persist independent scenario results immediately, including collector errors."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import os
import platform
import shutil
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from common import command, export_evidence, run_payload, target, write_json
from offline import measure_offline
from quarantine import measure_quarantine
from registry import measure_registry


def collect(action: Callable[[], Any]) -> Any:
    """Contain an independent collector failure without exposing credential data.

    Args:
        action: One scenario's operation.

    Returns:
        Observation, or a failed collector record with sanitized exception type.
    """
    try:
        return action()
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        TypeError,
        http.client.HTTPException,
    ) as error:
        return {"status": "fail", "collector_error": type(error).__name__}


def archive_digest(path: Path) -> str:
    """Hash a local build archive.

    Args:
        path: Built archive.

    Returns:
        SHA-256 of the actual archive bytes.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def footprint(
    *, root: Path, archive: Path, cold: list[dict[str, Any]]
) -> dict[str, Any]:
    """Collect payload size and narrow fresh-process timing observations.

    Args:
        root: Built payload tree.
        archive: Build archive.
        cold: Measured runtime observations.

    Returns:
        Size, file count and process wall times.
    """
    files = [path for path in root.rglob("*") if path.is_file()]
    return {
        "payload_bytes": sum(path.stat().st_size for path in files),
        "files": len(files),
        "archive_bytes": archive.stat().st_size,
        "fresh_process_seconds": [item.get("seconds") for item in cold],
        "disk_cold": "unverified: OS page cache not flushed",
    }


def quarantine_copy(
    *, root: Path, destination: Path, variant: str, home: Path
) -> dict[str, Any]:
    """Copy before marking so quarantine errors cannot alter the build.

    Args:
        root: Built payload.
        destination: Disposable quarantine tree.
        variant: ts or py.
        home: Disposable runtime HOME.

    Returns:
        Platform security observations.
    """
    shutil.copytree(src=root, dst=destination)
    return measure_quarantine(root=destination, variant=variant, home=home)


def main() -> None:
    """Collect measurements; a scenario failure cannot erase completed evidence."""
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
        "schema": 2,
        "target": target(),
        "platform": platform.platform(),
        "collected_utc": datetime.now(UTC).isoformat(),
        "source_head": head["stdout"].strip(),
        "source_status": status["stdout"],
        "expected_source_head": os.environ.get("SPIKE_SOURCE_SHA"),
        "collector_python": sys.executable,
        "acquisition": {
            key: os.environ.get(key)
            for key in (
                "SPIKE_DOWNLOAD_OUTCOME",
                "SPIKE_UNPACK_OUTCOME",
            )
        },
        "metadata_commands": records,
        "workflow_event": os.environ.get("GITHUB_EVENT_NAME"),
        "workflow_run": (
            f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
            if os.environ.get("GITHUB_RUN_ID")
            else None
        ),
        "note": "pass covers only the stated observation; unverified is not a pass",
    }
    evidence = {variant: {**metadata, "variant": variant} for variant in ("ts", "py")}
    suffix = "-offline" if args.offline_only else ""
    paths = {v: args.results / f"{target()}-{v}{suffix}.json" for v in evidence}

    def persist() -> None:
        """Save each variant after every independent scenario."""
        for variant, item in evidence.items():
            write_json(path=paths[variant], value=item)

    persist()
    try:
        expected = metadata["expected_source_head"]
        if (
            head["exit"] != 0
            or status["exit"] != 0
            or not metadata["source_head"]
            or (expected is not None and metadata["source_head"] != expected)
        ):
            for item in evidence.values():
                item.update(
                    status="invalid",
                    reason=(
                        "source head unavailable or differs from expected_source_head"
                    ),
                )
            persist()
            raise ValueError(
                "source head unavailable or differs from expected_source_head"
            )
        with tempfile.TemporaryDirectory(prefix="spike-measure-") as temporary:
            work = Path(temporary)
            offline_work = work / "offline"
            offline_work.mkdir()
            offline = collect(
                lambda: measure_offline(
                    build=build, work=offline_work, harden_block=args.offline_only
                )
            )
            for variant, item in evidence.items():
                item["offline"] = offline.get(variant, offline)
                item["archive_sha256"] = collect(
                    partial(archive_digest, build / f"{variant}.tgz")
                )
            persist()
            if not args.offline_only:
                for variant, item in evidence.items():
                    root = build / variant
                    entries: list[dict[str, Any]] = []
                    cold = [
                        collect(
                            partial(
                                run_payload,
                                root=root,
                                variant=variant,
                                home=work / f"{variant}-cold-{number}",
                                records=entries,
                            )
                        )
                        for number in range(3)
                    ]
                    item["no_node"] = {
                        "status": (
                            "pass"
                            if all(item["status"] == "pass" for item in cold)
                            else "fail"
                        ),
                        "processes": cold,
                        "commands": entries,
                        "scope": (
                            "Remove Node/Bun directories from PATH; "
                            "retain Windows loader "
                            "necessities. Tools are not physically uninstalled."
                        ),
                    }
                    persist()
                    item["footprint"] = collect(
                        partial(
                            footprint,
                            root=root,
                            archive=build / f"{variant}.tgz",
                            cold=cold,
                        )
                    )
                    persist()
                    quarantine_root = work / f"quarantine-{variant}"
                    item["quarantine"] = collect(
                        partial(
                            quarantine_copy,
                            root=root,
                            destination=quarantine_root,
                            variant=variant,
                            home=work / f"quarantine-home-{variant}",
                        )
                    )
                    persist()
                registry_work = work / "registry"
                registry_work.mkdir()
                registry = collect(
                    lambda: measure_registry(build=build, work=registry_work)
                )
                for variant, item in evidence.items():
                    item["private_registry"] = registry.get(variant, registry)
                    item["registry_server"] = registry.get("server", [])
                persist()
    finally:
        for path in paths.values():
            export_evidence(path)


if __name__ == "__main__":
    main()
