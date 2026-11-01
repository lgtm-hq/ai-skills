#!/usr/bin/env python3
"""Install local payload archives under measured OS network restrictions."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from common import SPIKE, command, isolated_env, run_payload, runtime, write_json


def measure_offline(
    *, build: Path, work: Path, harden_block: bool = False
) -> dict[str, Any]:
    """Attempt a real network-denied subprocess, retaining unsupported probe errors.

    Args:
        build: Directory containing both native archives and the Python runtime.
        work: Disposable evidence workspace.
        harden_block: Whether this is the dedicated empty-allowlist Linux job.

    Returns:
        Per-variant measured results or exact unverified reasons and probe outputs.
    """
    records: list[dict[str, Any]] = []
    python = runtime(root=build / "py", variant="py")[0]
    prefixes: list[list[str]] = []
    firewall: list[str] | None = None
    if platform.system() == "Linux":
        unshare = shutil.which("unshare")
        sudo = shutil.which("sudo")
        if unshare:
            prefixes.append([unshare, "--user", "--map-root-user", "--net", "--"])
            if sudo:
                prefixes.append([sudo, "-n", unshare, "--net", "--"])
    elif platform.system() == "Darwin":
        sandbox = shutil.which("sandbox-exec")
        if sandbox:
            prefixes.append(
                [sandbox, "-p", "(version 1)(allow default)(deny network*)"]
            )
    elif os.name == "nt":
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if shell:
            firewall = [shell, "-NoProfile", "-NonInteractive", "-Command"]
            rule = command(
                argv=[
                    *firewall,
                    (
                        "$ErrorActionPreference='Stop'; New-NetFirewallRule "
                        "-DisplayName 'InstallPlaneSpike-offline' -Direction Outbound "
                        "-Action Block -Profile Any"
                    ),
                ],
                records=records,
            )
            if rule["exit"] == 0:
                prefixes.append([])
    env = isolated_env(work)
    try:
        chosen = None
        for prefix in prefixes:
            probe = command(
                argv=[
                    *prefix,
                    python,
                    "-I",
                    "-B",
                    str(SPIKE / "scripts/network_control.py"),
                ],
                records=records,
                env=env,
                timeout=15,
            )
            if probe["exit"] == 0:
                chosen = prefix
                break
        if chosen is None:
            reason = (
                "OS denial unavailable or not proven (timeouts are inconclusive); "
                "inspect every attempted command"
            )
            if not prefixes:
                reason = (
                    f"no isolation tool on {platform.platform()}: requires "
                    "unshare, sandbox-exec or PowerShell firewall"
                )
            return {
                variant: {"status": "unverified", "reason": reason, "commands": records}
                for variant in ("ts", "py")
            }
        result_path = work / "offline-worker.json"
        run = command(
            argv=[
                *chosen,
                python,
                "-E",
                "-s",
                "-B",
                str(SPIKE / "scripts/offline.py"),
                "--worker",
                "--build",
                str(build),
                "--result",
                str(result_path),
            ],
            records=records,
            env=env,
            timeout=180,
        )
        if run["exit"] != 0 or not result_path.is_file():
            return {
                variant: {
                    "status": "fail",
                    "reason": "isolated local-file installation failed",
                    "commands": records,
                }
                for variant in ("ts", "py")
            }
        observed = json.loads(result_path.read_text())
        return {
            variant: {
                **observed[variant],
                "isolation": (
                    chosen if chosen else "temporary Windows outbound firewall rule"
                ),
                "harden_runner_empty_allowlist": harden_block,
                "isolation_commands": records,
            }
            for variant in ("ts", "py")
        }
    finally:
        if firewall:
            command(
                argv=[
                    *firewall,
                    (
                        "Get-NetFirewallRule -DisplayName 'InstallPlaneSpike-offline' "
                        "-ErrorAction SilentlyContinue | Remove-NetFirewallRule"
                    ),
                ],
                records=records,
            )


def main() -> None:
    """Run the offline installation worker, invoked only after isolation is proved."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    results = {}
    for variant in ("ts", "py"):
        with tempfile.TemporaryDirectory(
            prefix="spike-offline-", dir=args.result.parent
        ) as temp:
            work = Path(temp)
            records: list[dict[str, Any]] = []
            # Only relative directories and regular files are accepted. No links,
            # devices or archive-controlled ownership may affect the destination.
            with tarfile.open(args.build / f"{variant}.tgz", mode="r:gz") as archive:
                for member in archive:
                    relative = PurePosixPath(member.name)
                    destination = (work / member.name).resolve()
                    if (
                        relative.is_absolute()
                        or ".." in relative.parts
                        or "\\" in member.name
                        or ":" in member.name
                        or not destination.is_relative_to(work.resolve())
                        or not (member.isdir() or member.isfile())
                    ):
                        raise ValueError(f"unsafe bundle member: {member.name}")
                    if member.isdir():
                        destination.mkdir(parents=True, exist_ok=True)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        source = archive.extractfile(member)
                        if source is None:
                            raise ValueError("missing bundle file bytes")
                        with source, destination.open("wb") as output:
                            shutil.copyfileobj(fsrc=source, fdst=output)
                        destination.chmod(member.mode & 0o777)
            home = work / "home"
            home.mkdir()
            observed = run_payload(
                root=work / "payload", variant=variant, home=home, records=records
            )
            results[variant] = {
                **observed,
                "installation": "local .tgz regular-file copy with path validation",
                "commands": records,
            }
    write_json(path=args.result, value=results)


if __name__ == "__main__":
    main()
