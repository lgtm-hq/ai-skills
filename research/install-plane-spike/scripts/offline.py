#!/usr/bin/env python3
"""Measure real local-tarball package-manager installs under explicit isolation."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import uuid
from pathlib import Path, PureWindowsPath
from typing import Any

from common import (
    SETTINGS,
    SPIKE,
    command,
    isolated_env,
    run_payload,
    runtime,
    write_json,
)
from network_control import proven_denial
from packages import client_env, install_client, prepare_packages
from windows_control import finish as finish_windows_controls
from windows_control import prepare as prepare_windows_controls


def identity() -> dict[str, Any]:
    """Record actual worker privilege without relying on inherited USER strings.

    Returns:
        Effective POSIX identity or Windows account observation scope.
    """
    if os.name == "nt":
        return {
            "account": os.environ.get("USERNAME"),
            "effective_uid": None,
            "privilege": "Windows token elevation unverified",
        }
    return {
        "uid": os.getuid(),
        "effective_uid": os.geteuid(),
        "effective_gid": os.getegid(),
        "groups": os.getgroups(),
    }


def isolation_argv(
    *, prefix: list[str], argv: list[str], env: dict[str, str]
) -> list[str]:
    """Pass only explicit scenario environment after sudo resets its environment.

    Args:
        prefix: Selected namespace/sandbox prefix, ending in env -i for sudo.
        argv: Probe or worker invocation.
        env: Credential-free environment for this invocation.

    Returns:
        Complete command, restoring environment only after dropping privileges.
    """
    assignments = (
        [f"{key}={value}" for key, value in sorted(env.items())]
        if prefix and prefix[-1] == "-i"
        else []
    )
    return [*prefix, *assignments, *argv]


def transport_status(*, direct: dict[str, Any], npm: dict[str, Any]) -> str:
    """Apply the owner's direct-runtime plus npm-fallback offline rule.

    Args:
        direct: Standalone execution observation, without an installation step.
        npm: Local-file wrapper installation and execution observation.

    Returns:
        Fail for a known required failure, pass for both passes, else unverified.
        Bun local-file evidence is retained separately and never enters this gate.
    """
    statuses = [item.get("status", "unverified") for item in (direct, npm)]
    if "fail" in statuses:
        return "fail"
    return "pass" if all(status == "pass" for status in statuses) else "unverified"


def worker(
    *, build: Path, work: Path, packages_from: Path | None = None
) -> dict[str, Any]:
    """Run standalone payloads, then scripts-free local wrappers with both clients.

    Args:
        build: Original payloads (no extraction masquerading as installation).
        work: Fresh offline workspace.
        packages_from: Reuse the exact tarballs from the unrestricted control.

    Returns:
        Independent direct execution, per-client results and packing commands.
    """
    results: dict[str, dict[str, Any]] = {}
    consumer = identity()
    if consumer["effective_uid"] == 0:
        raise ValueError("refusing to measure package managers as root")
    bun = shutil.which("bun")
    for variant in ("ts", "py"):
        entries: list[dict[str, Any]] = []
        direct = run_payload(
            root=build / variant,
            variant=variant,
            home=work / f"direct-{variant}",
            records=entries,
        )
        results[variant] = {
            "identity": consumer,
            "status": transport_status(direct=direct, npm={}),
            "direct_execution": direct,
            "direct_commands": entries,
            "clients": {},
            "required_transports": ["direct_execution", "npm"],
            "bun_local_file_gate": False,
        }
        write_json(path=work / f"worker-{variant}.json", value=results[variant])
        entries = []
        packages = (packages_from or work) / f"packages-{variant}"
        required_archives = [
            packages / f"{variant}-{platform_target}.tgz"
            for platform_target in SETTINGS["targets"]
        ] + [packages / f"wrapper-{variant}.tgz"]
        packed = not packages_from or all(path.is_file() for path in required_archives)
        if packages_from is None:
            if bun is None:
                results[variant]["reason"] = "Bun unavailable for local packing"
                write_json(path=work / f"worker-{variant}.json", value=results[variant])
                continue
            directories = prepare_packages(
                build=build, work=packages, variant=variant, local=True
            )
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
            **results[variant],
            "package_source": str(packages),
            "status": transport_status(direct=direct, npm=clients.get("npm", {})),
            "clients": clients,
            "packing_commands": entries,
            "missing_archives": [
                str(path) for path in required_archives if not path.is_file()
            ],
            "installation": (
                "local npm wrapper with optional os/cpu tarball dependencies; "
                "fresh caches; ignore-scripts"
            ),
        }
        write_json(path=work / f"worker-{variant}.json", value=results[variant])
    return results


def firewall_program(path: Path) -> dict[str, Any]:
    """Resolve existing long-path identity before appending future install paths.

    Args:
        path: Explicit probe, client or future payload executable only.

    Returns:
        Requested and resolved identities for public command evidence.

    Raises:
        OSError: If an existing ancestor cannot be resolved.
        ValueError: For UNC, device, short-alias or non-executable identities.
    """
    ancestor = path
    suffix: list[str] = []
    while not ancestor.exists():
        if ancestor.parent == ancestor:
            raise ValueError(f"no existing program ancestor: {path}")
        suffix.insert(0, ancestor.name)
        ancestor = ancestor.parent
    # On Windows resolve(strict=True) uses a handle to expand RUNNER~1 and other
    # 8.3 aliases. Resolve the existing ancestor, not a not-yet-installed file.
    full = ancestor.resolve(strict=True).joinpath(*suffix)
    program = str(full)
    parsed = PureWindowsPath(program)
    if (
        not parsed.is_absolute()
        or not is_local_windows_drive(parsed.drive)
        or parsed.suffix.lower() != ".exe"
        or any(c in program for c in ("~", "*", "?", "\x00", "\r", "\n"))
    ):
        raise ValueError(f"unsafe firewall program identity: {program}")
    return {
        "requested": str(path),
        "program": program,
        "existing_ancestor": str(ancestor.resolve(strict=True)),
        "future_suffix": suffix,
        "exists": path.is_file(),
    }


def is_local_windows_drive(drive: str) -> bool:
    """Accept only an absolute local Windows drive, never UNC/device scopes.

    Args:
        drive: PureWindowsPath drive component.

    Returns:
        Whether the drive is a single ASCII letter and colon.
    """
    return (
        len(drive) == 2
        and drive[0].isascii()
        and drive[0].isalpha()
        and drive[1] == ":"
    )


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
    # Same tarball shape, flags and fresh caches before OS isolation. The dedicated
    # Harden Runner job has no unrestricted interval and cannot supply this control.
    positive_installs = (
        {
            v: {"status": "unverified", "reason": "no unrestricted interval"}
            for v in ("ts", "py")
        }
        if harden_block
        else worker(build=build, work=work / "positive-installs")
    )
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
            prefixes.append([unshare, "--user", "--map-current-user", "--net", "--"])
            setpriv, env_tool = shutil.which("setpriv"), shutil.which("env")
            if sudo and setpriv and env_tool and os.geteuid() != 0:
                prefixes.append(
                    [
                        sudo,
                        "-n",
                        unshare,
                        "--net",
                        "--",
                        setpriv,
                        "--reuid",
                        str(os.getuid()),
                        "--regid",
                        str(os.getgid()),
                        "--clear-groups",
                        "--",
                        env_tool,
                        "-i",
                    ]
                )
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
            "positive_installation_control": positive_installs[variant],
            "collector_identity": identity(),
            "probe_denial_proven": False,
            "installer_denial_proven": False,
            "direct_execution": {
                "status": "unverified",
                "reason": "restricted standalone runtime not yet observed",
            },
            "required_transports": ["direct_execution", "npm"],
            "bun_local_file_gate": False,
            "denial_scope": "requires matched runtime and installer controls",
            "commands": records,
            "cleanup": cleanup,
            "reason": (
                "Requires successful same-host IPv4 control then explicit denial; "
                "timeouts are inconclusive"
            ),
        }
        for variant in ("ts", "py")
    }
    program_controls: dict[str, Any] = {}
    try:
        if not harden_block and platform.system() == "Windows":
            shell = shutil.which("powershell") or shutil.which("pwsh")
            mechanism = "Windows per-program outbound firewall (not Harden Runner)"
            for result in results.values():
                result["mechanism"] = mechanism
            if shell:
                try:
                    program_controls = prepare_windows_controls(build=build, work=work)
                except OSError as error:
                    for result in results.values():
                        result["program_control_error"] = str(error)
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
                    *[runtime(root=build / v, variant=v)[0] for v in ("ts", "py")],
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
                try:
                    identities = [firewall_program(Path(p)) for p in sorted(programs)]
                except (OSError, ValueError) as error:
                    for result in results.values():
                        result["reason"] = (
                            f"firewall program normalization failed: {error}"
                        )
                    return results
                for result in results.values():
                    result["firewall_programs"] = identities
                literals = ",".join(
                    "'" + item["program"].replace("'", "''") + "'"
                    for item in identities
                )
                created = command(
                    argv=[
                        *firewall,
                        (
                            "$ErrorActionPreference='Stop'; "
                            f"@({literals}) | ForEach-Object {{ "
                            "Write-Output ('firewall program: ' + $_); "
                            "New-NetFirewallRule "
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
                else:
                    for result in results.values():
                        result["reason"] = (
                            f"firewall setup failed (exit {created['exit']}): "
                            + (
                                created.get("stderr", "").strip()
                                or created.get("error", "no diagnostic")
                            )
                        )
            else:
                for result in results.values():
                    result["reason"] = (
                        "PowerShell unavailable for scoped firewall setup"
                    )
        chosen = None
        proved = False
        for prefix in prefixes:
            restricted = command(
                argv=isolation_argv(prefix=prefix, argv=probe_argv, env=env),
                env=env,
                records=records,
                timeout=15,
            )
            proved = proven_denial(control=control, restricted=restricted)
            for result in results.values():
                result["restricted_probe"] = restricted
                result["probe_denial_proven"] = proved
                # Per-program rules do not share the probe's network boundary.
                # No matched Bun/Node/installed-runtime probes are performed here.
                result["installer_denial_proven"] = (
                    proved and platform.system() != "Windows"
                )
                result["denial_scope"] = (
                    "bundled Python probe only; Bun, Node and direct/installed runtime "
                    "rules have no same-program positive/restricted controls"
                    if platform.system() == "Windows"
                    else f"shared restriction: {mechanism}; matched control required"
                )
                if proved and not result["installer_denial_proven"]:
                    result["reason"] = result["denial_scope"]
            if proved or harden_block:
                chosen = prefix
                break
        if chosen is not None:
            result_path = work / "offline-worker.json"
            worker_env = client_env(
                client=work / "worker-env", registry="http://127.0.0.1:9"
            )
            run = command(
                argv=isolation_argv(
                    prefix=chosen,
                    env=worker_env,
                    argv=[
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
                        *(
                            []
                            if harden_block
                            else ["--packages-from", str(work / "positive-installs")]
                        ),
                    ],
                ),
                records=records,
                env=worker_env,
                timeout=600,
            )
            if run["exit"] == 0 and result_path.is_file():
                observed = json.loads(result_path.read_text(encoding="utf-8"))
                if program_controls:
                    denials = finish_windows_controls(
                        controls=program_controls, work=work
                    )
                    for variant in ("ts", "py"):
                        npm_commands = (
                            observed[variant]
                            .get("clients", {})
                            .get("npm", {})
                            .get("commands", [])
                        )
                        launcher = program_controls["npm-node"]["npm_launcher"]
                        same_launcher = bool(
                            len(launcher) == 2
                            and npm_commands
                            and npm_commands[0].get("argv", [])[:2] == launcher
                        )
                        results[variant].update(
                            program_controls=program_controls,
                            npm_launcher_matches_control=same_launcher,
                            installer_denial_proven=(
                                denials[variant] and same_launcher
                            ),
                            denial_scope=(
                                "matched executable path/bytes and IPv4 controls for "
                                "direct runtime, actual npm Node launcher and "
                                "installed npm payload only; informational Bun "
                                "remains unverified"
                            ),
                        )
                for variant in ("ts", "py"):
                    results[variant]["installation_observation"] = observed[variant]
                    execution = observed[variant].get("direct_execution", {})
                    results[variant]["direct_execution"] = {
                        "status": (
                            execution.get("status", "unverified")
                            if results[variant]["installer_denial_proven"]
                            else "unverified"
                        ),
                        "execution": execution,
                        "commands": observed[variant].get("direct_commands", []),
                        "denial_proven": results[variant]["installer_denial_proven"],
                        "scope": "original standalone payload; no install step",
                    }
                    if results[variant]["installer_denial_proven"]:
                        results[variant].update(
                            status=transport_status(
                                direct=execution,
                                npm=observed[variant].get("clients", {}).get("npm", {}),
                            ),
                            reason=None,
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
                    result["direct_execution"].update(
                        status="unverified",
                        denial_proven=False,
                        reason="firewall cleanup not verified",
                    )
                    result.update(
                        status="unverified",
                        reason=f"{result.get('reason') or 'restriction measured'}; "
                        "firewall cleanup not verified",
                    )
    return results


def main() -> None:
    """Run the already isolated package-manager worker with setup tools on PATH."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--setup-path", required=True)
    parser.add_argument("--packages-from", type=Path)
    args = parser.parse_args()
    # sudo may reset PATH before entering a namespace. Only setup tools use this;
    # installed runtime execution still uses its own filtered environment.
    os.environ["PATH"] = args.setup_path
    work = args.result.parent / "installs"
    work.mkdir()
    results = worker(build=args.build, work=work, packages_from=args.packages_from)
    write_json(path=args.result, value=results)


if __name__ == "__main__":
    main()
