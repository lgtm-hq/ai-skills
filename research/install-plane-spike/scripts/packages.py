#!/usr/bin/env python3
"""Shared scripts-free npm transport for registry and offline measurements."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from common import SETTINGS, command, payload_inventory, run_payload, target, write_json


def prepare_packages(
    *, build: Path, work: Path, variant: str, local: bool = False
) -> list[Path]:
    """Create one wrapper and optional os/cpu packages, without authored JS.

    Args:
        build: Built payload directory.
        work: Fresh package workspace.
        variant: ts or py.
        local: Use local tarball optional dependencies for the offline scenario.

    Returns:
        Platform package directories followed by their wrapper.
    """
    directories = []
    for item in SETTINGS["targets"]:
        path = work / f"{variant}-{item}"
        system, cpu = item.split("-")
        write_json(
            path=path / "package.json",
            value={
                "name": f"@spike/{variant}-{item}",
                "version": "0.0.1",
                "os": ["win32" if system == "windows" else system],
                "cpu": [cpu],
                "files": ["payload"],
            },
        )
        if item == target():
            shutil.copytree(src=build / variant, dst=path / "payload")
        directories.append(path)
    wrapper = work / f"wrapper-{variant}"
    write_json(
        path=wrapper / "package.json",
        value={
            "name": f"@spike/{variant}",
            "version": "0.0.1",
            "optionalDependencies": {
                f"@spike/{variant}-{item}": (
                    f"file:{(work / f'{variant}-{item}.tgz').as_posix()}"
                    if local
                    else "0.0.1"
                )
                for item in SETTINGS["targets"]
            },
        },
    )
    return [*directories, wrapper]


def client_env(*, client: Path, registry: str) -> dict[str, str]:
    """Create isolated client config/cache/HOME while retaining setup tool PATH.

    Args:
        client: Fresh client directory.
        registry: Explicit test registry (loopback only).

    Returns:
        Allowlisted environment with no inherited npm configuration or credentials.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE"}
    }
    home = client / "home"
    home.mkdir(parents=True, exist_ok=True)
    config = client / ".npmrc"
    config.write_text(
        f"registry={registry}\nignore-scripts=true\naudit=false\nfund=false\n",
        encoding="utf-8",
    )
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        TMP=str(home),
        TEMP=str(home),
        TMPDIR=str(home),
        APPDATA=str(home / "AppData/Roaming"),
        LOCALAPPDATA=str(home / "AppData/Local"),
        NPM_CONFIG_USERCONFIG=str(config),
        NPM_CONFIG_GLOBALCONFIG=str(client / "global-npmrc"),
        NPM_CONFIG_CACHE=str(client / "npm-cache"),
        NPM_CONFIG_REGISTRY=registry,
        BUN_INSTALL_CACHE_DIR=str(client / "bun-cache"),
        BUN_CONFIG_NO_CLEAR_TERMINAL="1",
    )
    return env


def install_client(
    *,
    build: Path,
    client: Path,
    variant: str,
    tool: str,
    dependency: str,
    registry: str,
    offline: bool = False,
) -> dict[str, Any]:
    """Install via the measured Bun/npm client and verify actual transported bytes.

    Args:
        build: Original payloads for comparison.
        client: Fresh isolated cache/client directory.
        variant: ts or py.
        tool: bun or npm; npm is a measured target, not repo dependency management.
        dependency: Registry version or local wrapper tarball.
        registry: Explicit loopback registry.
        offline: Request client offline behavior in addition to OS isolation.

    Returns:
        Exact command, transport digest/mode comparison and executable observation.
    """
    entries: list[dict[str, Any]] = []
    env = client_env(client=client, registry=registry)
    write_json(
        path=client / "package.json",
        value={"private": True, "dependencies": {f"@spike/{variant}": dependency}},
    )
    executable = shutil.which(tool)
    if executable is None:
        return {"status": "unverified", "reason": f"{tool} absent from setup PATH"}
    argv = [executable, "install", "--ignore-scripts"]
    if tool == "npm":
        argv += ["--no-audit", "--no-fund"]
    if offline:
        # Bun's flag availability is itself observed, never inferred as success.
        argv += ["--offline"]
    argv += ["--registry", registry]
    installed = command(argv=argv, cwd=client, env=env, records=entries, timeout=300)
    payload = client / "node_modules" / f"@spike/{variant}-{target()}" / "payload"
    expected = payload_inventory(build / variant)
    actual = payload_inventory(payload)
    same = bool(expected) and actual == expected
    selected = [
        item
        for item in SETTINGS["targets"]
        if (client / "node_modules" / f"@spike/{variant}-{item}").is_dir()
    ]
    selection_matches = selected == [target()]
    observation = None
    if installed["exit"] == 0 and same:
        observation = run_payload(
            root=payload, variant=variant, home=client / "runtime-home", records=entries
        )
    return {
        "status": (
            "pass"
            if observation and observation["status"] == "pass" and selection_matches
            else "fail"
        ),
        "commands": entries,
        "installed_platform_packages": selected,
        "platform_filter_matches_target": selection_matches,
        "payload_matches_build": same,
        "installed_inventory": {
            "files": len(actual),
            "tree_sha256": hashlib.sha256(
                json.dumps(actual, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        },
        "longest_installed_path": max(
            (str(p) for p in payload.rglob("*") if p.is_file()), key=len, default=""
        ),
        "observation": observation,
        "reason": (
            "installed payload bytes/modes differ or optional package omitted"
            if not same
            else (
                None
                if selection_matches
                else "incompatible platform packages installed"
            )
        ),
    }
