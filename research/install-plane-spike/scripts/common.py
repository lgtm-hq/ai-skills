#!/usr/bin/env python3
"""Shared measurement plumbing; all external commands preserve raw output."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess  # nosec B404 - experiment commands use explicit argv, never a shell
import time
from pathlib import Path
from typing import Any

SPIKE = Path(__file__).resolve().parents[1]
REPO = SPIKE.parents[1]
SETTINGS = json.loads((SPIKE / "settings.json").read_text())


def target() -> str:
    """Get this process's supported OS/architecture pair.

    Returns:
        Bun target suffix and npm platform identity.

    Raises:
        ValueError: If this runner is outside the experiment matrix.
    """
    system = {"Darwin": "darwin", "Linux": "linux", "Windows": "windows"}[
        platform.system()
    ]
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}[
        platform.machine().lower()
    ]
    value = f"{system}-{arch}"
    if value not in SETTINGS["targets"]:
        raise ValueError(f"unsupported target: {value}")
    return value


def command(
    *,
    argv: list[str],
    records: list[dict[str, Any]],
    cwd: Path = REPO,
    env: dict[str, str] | None = None,
    timeout: int = 120,
    redactions: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Execute a command without hiding failures or trimming output.

    Args:
        argv: Explicit executable and arguments; no shell expansion.
        records: Destination for the complete command record.
        cwd: Working directory.
        env: Child environment; None retains the setup environment.
        timeout: Maximum wall-clock seconds.
        redactions: Ephemeral secrets to remove before logging or retaining output.

    Returns:
        Command, exit code (None if not launched/completed), output and duration.
    """
    start = time.perf_counter()
    result: dict[str, Any] = {"argv": argv, "cwd": str(cwd)}
    try:
        process = subprocess.run(  # nosec B603 - explicit experiment argv, no shell
            args=argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        result.update(
            exit=process.returncode, stdout=process.stdout, stderr=process.stderr
        )
    except subprocess.TimeoutExpired as error:
        result.update(
            exit=None,
            stdout=(error.stdout or b"").decode(errors="replace"),
            stderr=(error.stderr or b"").decode(errors="replace"),
            error="timeout",
        )
    except OSError as error:
        result.update(
            exit=None, stdout="", stderr=str(error), error=type(error).__name__
        )
    result["seconds"] = time.perf_counter() - start
    for key in ("stdout", "stderr"):
        for secret in redactions:
            if secret:
                result[key] = result[key].replace(secret, "[redacted]")
    records.append(result)
    print(json.dumps(result), flush=True)
    return result


def checked(*, argv: list[str], records: list[dict[str, Any]], cwd: Path = REPO) -> str:
    """Run setup/build tooling, aborting on failure.

    Args:
        argv: Explicit command and arguments.
        records: Complete command log.
        cwd: Working directory.

    Returns:
        Untrimmed stdout.

    Raises:
        RuntimeError: If setup/build failed.
    """
    result = command(argv=argv, records=records, cwd=cwd, timeout=600)
    if result["exit"] != 0:
        raise RuntimeError(f"setup/build command failed: {argv}")
    return str(result["stdout"])


def runtime(*, root: Path, variant: str) -> list[str]:
    """Get the absolute invocation of an unpacked self-contained payload.

    Args:
        root: Variant payload root.
        variant: ts or py.

    Returns:
        Runtime invocation, without fixture arguments.
    """
    if variant == "ts":
        return [str(root / ("spike.exe" if os.name == "nt" else "spike"))]
    executable = root / "runtime" / ("python.exe" if os.name == "nt" else "bin/python3")
    return [str(executable), "-I", "-B", str(root / "prototype.py")]


def isolated_env(home: Path) -> dict[str, str]:
    """Create a credential-free runtime environment with no Node/Bun on PATH.

    Args:
        home: Disposable HOME containing writable temporary directories.

    Returns:
        Credential-free environment retaining Windows loader necessities and a
        control PATH with directories containing Node/Bun removed.
    """
    env = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "PATHEXT")
        if key in os.environ
    }
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        PATH=os.pathsep.join(
            directory
            for directory in os.environ.get("PATH", "").split(os.pathsep)
            if directory
            and not any(
                (Path(directory.strip('"')) / name).is_file()
                for name in (
                    "node",
                    "node.exe",
                    "node.cmd",
                    "bun",
                    "bun.exe",
                    "bun.cmd",
                )
            )
        ),
        LOCALAPPDATA=str(home / "AppData/Local"),
        APPDATA=str(home / "AppData/Roaming"),
        TMP=str(home),
        TEMP=str(home),
        TMPDIR=str(home),
    )
    return env


def write_json(*, path: Path, value: object) -> None:
    """Write an evidence document without platform newline differences.

    Args:
        path: Destination JSON file.
        value: JSON-serializable evidence.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def payload_inventory(root: Path) -> dict[str, dict[str, object]]:
    """Hash actual package contents and executable bits for transport comparison.

    Args:
        root: Built or installed payload tree.

    Returns:
        Relative filenames mapped to SHA-256 and portable executable-bit state.
    """
    return {
        path.relative_to(root).as_posix(): {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "executable": (
                bool(path.stat().st_mode & 0o111) if os.name != "nt" else None
            ),
        }
        for path in root.rglob("*")
        if path.is_file()
    }


def export_evidence(path: Path) -> None:
    """Publish raw JSON through runner log/summary without artifact egress.

    Args:
        path: Completed evidence JSON.
    """
    raw = path.read_text(encoding="utf-8")
    print(f"EVIDENCE {path.name}\n{raw}", flush=True)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as output:
            output.write(f"\n### {path.name}\n\n```json\n{raw}\n```\n")


def run_payload(
    *,
    root: Path,
    variant: str,
    home: Path,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measure an isolated process and compare stdout and on-disk output.

    Args:
        root: Installed payload root.
        variant: ts or py.
        home: Disposable HOME.
        records: Complete command/output log.

    Returns:
        Verified outcome and observed HOME cache writes.
    """
    home.mkdir(parents=True, exist_ok=True)
    cache = home / ".cache"
    cache.write_text("cache directory intentionally unavailable")
    env = isolated_env(home)
    env.update(XDG_CACHE_HOME=str(cache), BUN_INSTALL_CACHE_DIR=str(cache))
    result = command(
        argv=[
            *runtime(root=root, variant=variant),
            str(root / "fixtures"),
            SETTINGS["exclude"],
        ],
        cwd=home,
        env=env,
        records=records,
    )
    expected = json.loads((root / "fixtures/expected-output.json").read_text())
    destination = home / ".spike-target"
    actual = {
        p.relative_to(destination).as_posix(): p.read_bytes().decode("utf-8")
        for p in destination.rglob("*")
        if p.is_file()
    }
    try:
        stdout_matches = json.loads(result["stdout"]) == expected
    except (ValueError, TypeError):
        stdout_matches = False
    return {
        "status": (
            "pass"
            if result["exit"] == 0 and stdout_matches and actual == expected
            else "fail"
        ),
        "seconds": result["seconds"],
        "exit": result["exit"],
        "PATH": env["PATH"],
        "cache_directory_blocked": True,
        "other_HOME_files": [
            p.relative_to(home).as_posix()
            for p in home.rglob("*")
            if p.is_file() and p != cache and destination not in p.parents
        ],
        "cache_scope": (
            "HOME only; writes elsewhere and read-only runtime trees unverified"
        ),
    }
