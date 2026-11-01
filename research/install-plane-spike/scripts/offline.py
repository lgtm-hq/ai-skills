#!/usr/bin/env python3
"""Measure real local-tarball package-manager installs under explicit isolation."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import uuid
from pathlib import Path
from typing import Any

from common import SPIKE, command, isolated_env, runtime, write_json
from network_control import proven_denial
from packages import client_env, install_client, prepare_packages


def worker(*, build: Path, work: Path) -> dict[str, Any]:
    """Pack scripts-free wrappers and install local tarballs using both clients.

    Args:
        build: Original payloads (no extraction masquerading as installation).
        work: Fresh offline workspace.

    Returns:
        Per-client results and packing commands for each runtime.
    """
    results: dict[str, dict[str, Any]] = {}
    bun = shutil.which("bun")
    for variant in ("ts", "py"):
        entries: list[dict[str, Any]] = []
        if bun is None:
            results[variant] = {
                "status": "unverified",
                "reason": "Bun unavailable for local packing",
            }
            continue
        packages = work / f"packages-{variant}"
        directories = prepare_packages(
            build=build, work=packages, variant=variant, local=True
        )
        packed = True
        for directory in directories:
            archive = packages / f"{directory.name}.tgz"
            result = command(
                argv=[
                    bun,
                    "pm",
                    "pack",
                    "--ignore-scripts",
                    "--quiet",
                    "--filename",
                    str(archive),
                ],
                cwd=directory,
                env=client_env(
                    client=work / f"pack-{directory.name}",
                    registry="http://127.0.0.1:9",
                ),
                records=entries,
                timeout=300,
            )
            packed = packed and result["exit"] == 0 and archive.is_file()
        clients = {}
        if packed:
            wrapper_archive = packages / f"wrapper-{variant}.tgz"
            for tool in ("bun", "npm"):
                clients[tool] = install_client(
                    build=build,
                    client=work / f"client-{variant}-{tool}",
                    variant=variant,
                    tool=tool,
                    dependency=f"file:{wrapper_archive.as_posix()}",
                    registry="http://127.0.0.1:9",
                    offline=True,
                )
        results[variant] = {
            "status": (
                "pass"
                if clients
                and all(item["status"] == "pass" for item in clients.values())
                else "fail"
            ),
            "clients": clients,
            "packing_commands": entries,
            "installation": (
                "local npm wrapper with optional os/cpu tarball dependencies; "
                "fresh caches; ignore-scripts"
            ),
        }
        write_json(path=work / f"worker-{variant}.json", value=results[variant])
    return results


def measure_offline(
    *, build: Path, work: Path, harden_block: bool = False
) -> dict[str, Any]:
    """Compare identical positive/restricted probes and preserve uncertain results.

    Args:
        build: Both native payloads and their bundled Python interpreter.
        work: Disposable scenario directory.
        harden_block: Dedicated first-step Harden Runner empty-allowlist job.

    Returns:
        Per-variant evidence including independent restriction and install outcomes.
    """
    records: list[dict[str, Any]] = []
    python = runtime(root=build / "py", variant="py")[0]
    probe_argv = [python, "-I", "-B", str(SPIKE / "scripts/network_control.py")]
    env = isolated_env(work)
    control = (
        {
            "exit": None,
            "stdout": "",
            "reason": (
                "First-step Harden Runner already active; "
                "no same-host unrestricted control"
            ),
        }
        if harden_block
        else command(argv=probe_argv, env=env, records=records, timeout=15)
    )
    prefixes: list[list[str]] = []
    mechanism = "unavailable"
    if harden_block:
        prefixes = [[]]
        mechanism = "Harden Runner directly; no namespace/sandbox/firewall prefix"
    elif platform.system() == "Linux":
        mechanism = "Linux network namespace (not Harden Runner)"
        unshare, sudo = shutil.which("unshare"), shutil.which("sudo")
        if unshare:
            prefixes.append([unshare, "--user", "--map-root-user", "--net", "--"])
            if sudo:
                prefixes.append([sudo, "-n", unshare, "--net", "--"])
    elif platform.system() == "Darwin":
        mechanism = "macOS sandbox-exec (not Harden Runner)"
        if sandbox := shutil.which("sandbox-exec"):
            prefixes = [[sandbox, "-p", "(version 1)(allow default)(deny network*)"]]
    firewall = None
    name = f"InstallPlaneSpike-{uuid.uuid4()}"
    cleanup: dict[str, Any] = {"status": "not applicable"}
    results: dict[str, dict[str, Any]] = {
        variant: {
            "status": "unverified",
            "mechanism": mechanism,
            "harden_runner_empty_allowlist_configured": harden_block,
            "positive_control": control,
            "denial_proven": False,
            "commands": records,
            "cleanup": cleanup,
            "reason": (
                "Requires successful same-host IPv4 control then explicit denial; "
                "timeouts are inconclusive"
            ),
        }
        for variant in ("ts", "py")
    }
    try:
        if not harden_block and platform.system() == "Windows":
            shell = shutil.which("powershell") or shutil.which("pwsh")
            mechanism = "Windows per-program outbound firewall (not Harden Runner)"
            for result in results.values():
                result["mechanism"] = mechanism
            if shell:
                firewall = [shell, "-NoProfile", "-NonInteractive", "-Command"]
                command(
                    argv=[
                        *firewall,
                        (
                            "Get-NetFirewallProfile | Select-Object "
                            "Name,Enabled,DefaultOutboundAction | ConvertTo-Json; "
                            "Get-NetConnectionProfile | Select-Object "
                            "InterfaceAlias,NetworkCategory,IPv4Connectivity,"
                            "IPv6Connectivity | ConvertTo-Json"
                        ),
                    ],
                    records=records,
                )
                # Never block the runner agent/control plane. Scope to the probe,
                # both package managers, and the exact subsequently installed runtimes.
                programs = {
                    python,
                    *[p for p in (shutil.which("bun"), shutil.which("node")) if p],
                }
                for variant in ("ts", "py"):
                    for tool in ("bun", "npm"):
                        payload = (
                            work
                            / "installs"
                            / f"client-{variant}-{tool}"
                            / "node_modules"
                            / f"@spike/{variant}-windows-x64"
                            / "payload"
                        )
                        programs.add(runtime(root=payload, variant=variant)[0])
                literals = ",".join(
                    "'" + p.replace("'", "''") + "'" for p in sorted(programs)
                )
                created = command(
                    argv=[
                        *firewall,
                        (
                            "$ErrorActionPreference='Stop'; "
                            f"@({literals}) | ForEach-Object {{ New-NetFirewallRule "
                            f"-DisplayName '{name}' -Direction Outbound "
                            "-Action Block -Profile Any -Program $_ "
                            "-ErrorAction Stop }; "
                            f"Get-NetFirewallRule -DisplayName '{name}' | "
                            "Get-NetFirewallApplicationFilter | ConvertTo-Json"
                        ),
                    ],
                    records=records,
                )
                if created["exit"] == 0:
                    prefixes = [[]]
        chosen = None
        proved = False
        for prefix in prefixes:
            restricted = command(
                argv=[*prefix, *probe_argv], env=env, records=records, timeout=15
            )
            proved = proven_denial(control=control, restricted=restricted)
            for result in results.values():
                result["restricted_probe"] = restricted
                result["denial_proven"] = proved
            if proved or harden_block:
                chosen = prefix
                break
        if chosen is not None:
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
                    "--setup-path",
                    os.environ.get("PATH", ""),
                ],
                records=records,
                env=client_env(
                    client=work / "worker-env", registry="http://127.0.0.1:9"
                ),
                timeout=600,
            )
            if run["exit"] == 0 and result_path.is_file():
                observed = json.loads(result_path.read_text(encoding="utf-8"))
                for variant in ("ts", "py"):
                    results[variant]["installation_observation"] = observed[variant]
                    if proved:
                        results[variant].update(
                            status=observed[variant]["status"], reason=None
                        )
            else:
                for result in results.values():
                    result["installation_error"] = (
                        "worker failed; partial worker JSON retained where available"
                    )
        for variant in ("ts", "py"):
            partial = work / "installs" / f"worker-{variant}.json"
            if partial.is_file():
                results[variant]["partial_installation"] = json.loads(
                    partial.read_text(encoding="utf-8")
                )
    finally:
        if firewall:
            removed = command(
                argv=[
                    *firewall,
                    (
                        "$ErrorActionPreference='Stop'; "
                        "Get-NetFirewallRule -ErrorAction Stop | "
                        f"Where-Object DisplayName -eq '{name}' | "
                        "Remove-NetFirewallRule -ErrorAction Stop; "
                        "$remaining=@(Get-NetFirewallRule -ErrorAction Stop | "
                        f"Where-Object DisplayName -eq '{name}'); "
                        "$remaining | Format-List *; "
                        "if ($remaining.Count -ne 0) { exit 1 }; "
                        "Write-Output 'rules absent'"
                    ),
                ],
                records=records,
            )
            cleanup.update(
                status=(
                    "verified removed" if removed["exit"] == 0 else "unverified removal"
                ),
                command=removed,
            )
            if removed["exit"] != 0:
                for result in results.values():
                    result.update(
                        status="unverified", reason="firewall cleanup not verified"
                    )
    return results


def main() -> None:
    """Run the already isolated package-manager worker with setup tools on PATH."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--setup-path", required=True)
    args = parser.parse_args()
    # sudo may reset PATH before entering a namespace. Only setup tools use this;
    # installed runtime execution still uses its own filtered environment.
    os.environ["PATH"] = args.setup_path
    work = args.result.parent / "installs"
    work.mkdir()
    results = worker(build=args.build, work=work)
    write_json(path=args.result, value=results)


if __name__ == "__main__":
    main()
