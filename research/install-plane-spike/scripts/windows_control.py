#!/usr/bin/env python3
"""Matched controls for required Windows offline executables; never fleet probes."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from common import SPIKE, command, runtime
from network_control import proven_denial
from packages import client_env, npm_launch


def observe(*, argv: list[str], home: Path) -> dict[str, Any]:
    """Record the exact executable identity and its diagnostic result.

    Args:
        argv: Fixed diagnostic command, never a caller-selected network target.
        home: Disposable config, cache and HOME directory.

    Returns:
        Command plus resolved executable digest; missing identities stay unknown.
    """
    try:
        executable = Path(argv[0]).resolve(strict=True)
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    except (OSError, IndexError) as error:
        return {"status": "unverified", "reason": str(error)}
    return {
        "program": str(executable),
        "sha256": digest,
        "command": command(
            argv=argv,
            env=client_env(client=home, registry="http://127.0.0.1:9"),
            records=[],
            timeout=15,
        ),
    }


def prepare(*, build: Path, work: Path) -> dict[str, Any]:
    """Probe exact future npm payload paths before rules, then remove seeded trees.

    Args:
        build: Original A/B payloads plus the emitted TypeScript Node diagnostic.
        work: Owned disposable offline scenario root.

    Returns:
        Baselines and identical argv for restricted controls after real installs.
        Seeding is a diagnostic, never an installation or scenario pass.
    """
    controls: dict[str, Any] = {}
    seeded = work / "installs"
    # Refuse to delete any existing tree. main() later creates a fresh installs
    # directory with fresh clients/caches for the actual restricted worker.
    seeded.mkdir(parents=True, exist_ok=False)
    try:
        for variant in ("ts", "py"):
            installed = (
                seeded
                / f"client-{variant}-npm"
                / "node_modules"
                / f"@spike/{variant}-windows-x64"
                / "payload"
            )
            shutil.copytree(src=build / variant, dst=installed)
            for name, root in (
                (f"direct-{variant}", build / variant),
                (f"npm-{variant}", installed),
            ):
                executable = runtime(root=root, variant=variant)[0]
                argv = (
                    [executable, "--spike-network-control"]
                    if variant == "ts"
                    else [
                        executable,
                        "-I",
                        "-B",
                        str(SPIKE / "scripts/network_control.py"),
                    ]
                )
                controls[name] = {"argv": argv}
        launcher = npm_launch()
        controls["npm-node"] = {
            "argv": (
                [
                    launcher[0],
                    str(build / "network-control.mjs"),
                    "--spike-network-control",
                ]
                if len(launcher) == 2
                else []
            ),
            "npm_launcher": launcher,
        }
        for name, item in controls.items():
            item["control"] = observe(
                argv=item["argv"],
                home=work / "program-controls" / name,
            )
    finally:
        shutil.rmtree(seeded)
    return controls


def finish(*, controls: dict[str, Any], work: Path) -> dict[str, bool]:
    """Require same-path/same-byte connected-to-denied pairs for each required route.

    Args:
        controls: Baselines from before rule creation; augmented with raw results.
        work: Same disposable root, after actual restricted npm installation.

    Returns:
        Per-variant direct-plus-npm denial proof. Informational Bun is excluded.
    """
    for name, item in controls.items():
        before = item["control"]
        after = observe(argv=item["argv"], home=work / "program-controls" / name)
        item["restricted"] = after
        item["denial_proven"] = bool(
            before.get("program")
            and before.get("program") == after.get("program")
            and before.get("sha256") == after.get("sha256")
            and proven_denial(
                control=before.get("command", {}),
                restricted=after.get("command", {}),
            )
        )
    return {
        variant: all(
            controls.get(name, {}).get("denial_proven", False)
            for name in (f"direct-{variant}", f"npm-{variant}", "npm-node")
        )
        for variant in ("ts", "py")
    }
