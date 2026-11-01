#!/usr/bin/env python3
"""Shared measurement plumbing; all external commands preserve raw output."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import subprocess  # nosec B404 - experiment commands use explicit argv, never a shell
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from process_tree import close_process, launch_process, stop_process_tree

SPIKE = Path(__file__).resolve().parents[1]
REPO = SPIKE.parents[1]
SETTINGS = json.loads((SPIKE / "settings.json").read_text(encoding="utf-8"))


def registry_setup_environment() -> dict[str, str]:
    """Capture trusted setup cache paths for bun x, never for measured clients.

    Returns:
        Explicit setup temp and Bun package-cache identity.
    """
    return {
        **{
            key: os.environ.get(key, tempfile.gettempdir())
            for key in ("TMPDIR", "TEMP", "TMP")
        },
        "BUN_INSTALL_CACHE_DIR": os.environ.get(
            "BUN_INSTALL_CACHE_DIR", str(Path.home() / ".bun/install/cache")
        ),
    }


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
    process = None
    try:
        process = launch_process(
            args=argv,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            result["tree_termination"] = stop_process_tree(process)
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                result["termination_error"] = "pipe EOF timeout after tree termination"
                raise
            raise subprocess.TimeoutExpired(argv, timeout, output=stdout, stderr=stderr)
        result.update(
            exit=process.returncode,
            stdout=output_text(stdout),
            stderr=output_text(stderr),
        )
    except subprocess.TimeoutExpired as error:
        result.update(
            exit=None,
            stdout=output_text(error.stdout),
            stderr=output_text(error.stderr),
            error="timeout",
        )
    except OSError as error:
        result.update(
            exit=None, stdout="", stderr=str(error), error=type(error).__name__
        )
    finally:
        if process is not None:
            try:
                if getattr(process, "job", None):
                    result["tree_termination"] = stop_process_tree(process)
                    if result["tree_termination"]["status"] != "pass":
                        result.update(exit=None, error="job cleanup not verified")
            finally:
                try:
                    close_process(process)
                except OSError as error:
                    result.update(
                        exit=None,
                        error="process handle cleanup failed",
                        cleanup_error=str(error),
                    )
    result["seconds"] = time.perf_counter() - start
    for key in ("stdout", "stderr"):
        for secret in redactions:
            if secret:
                result[key] = result[key].replace(secret, "[redacted]")
    records.append(result)
    print(json.dumps(result), flush=True)
    return result


def output_text(value: str | bytes | None) -> str:
    """Decode timeout output, which may be bytes even with text-mode pipes.

    Args:
        value: Partial subprocess output.

    Returns:
        UTF-8 text with undecodable bytes replaced.
    """
    return (
        value.decode("utf-8", errors="replace")
        if isinstance(value, bytes)
        else value or ""
    )


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
                for name in tool_names(os.environ)
            )
        ),
        LOCALAPPDATA=str(home / "AppData/Local"),
        APPDATA=str(home / "AppData/Roaming"),
        TMP=str(home),
        TEMP=str(home),
        TMPDIR=str(home),
    )
    return env


def tool_names(env: Mapping[str, str]) -> set[str]:
    """Return the same runtime aliases and suffixes for filtering and detection.

    Args:
        env: Explicit environment supplying Windows executable extensions.

    Returns:
        Bare aliases plus PATHEXT names (also conservatively filtered on POSIX).
    """
    names = {"node", "nodejs", "bun", "bunx"}
    return names | {
        tool + suffix.strip().lower()
        for tool in names
        for suffix in env.get("PATHEXT", ".EXE;.CMD;.BAT;.COM").split(";")
    }


def write_json(*, path: Path, value: object) -> None:
    """Write an evidence document without platform newline differences.

    Args:
        path: Destination JSON file.
        value: JSON-serializable evidence.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


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
        with Path(summary).open("a", encoding="utf-8", newline="\n") as output:
            output.write(f"\n### {path.name}\n\n```json\n{raw}\n```\n")


def installed_tree_matches(*, root: Path, expected: dict[str, str]) -> bool:
    """Compare the exact disposable output tree without traversing symlinks.

    Args:
        root: Target created by the now-stopped payload.
        expected: Trusted golden regular-file paths and UTF-8 contents.

    Returns:
        Whether the root, required directories, regular files and bytes match.
        Unexpected entries are rejected before descent or content reads. This
        post-execution check does not provide a concurrent filesystem sandbox.
    """
    directories = {
        parent.as_posix()
        for name in expected
        for parent in Path(name).parents
        if parent != Path(".")
    }
    seen_files: set[str] = set()
    seen_directories: set[str] = set()
    pending = [root]
    try:
        if not stat.S_ISDIR(root.lstat().st_mode):
            return False
        while pending:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    name = path.relative_to(root).as_posix()
                    mode = path.lstat().st_mode
                    if stat.S_ISDIR(mode) and name in directories:
                        seen_directories.add(name)
                        pending.append(path)
                    elif stat.S_ISREG(mode) and name in expected:
                        wanted = expected[name].encode("utf-8")
                        with path.open("rb") as stream:
                            if stream.read(len(wanted) + 1) != wanted:
                                return False
                        seen_files.add(name)
                    else:
                        return False
    except OSError:
        return False
    return seen_files == set(expected) and seen_directories == directories


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
    blocker = b"cache directory intentionally unavailable"
    cache.write_bytes(blocker)
    env = isolated_env(home)
    env.update(XDG_CACHE_HOME=str(cache), BUN_INSTALL_CACHE_DIR=str(cache))
    # cwd=HOME below: check Windows current-directory search there too, never in
    # the collector cwd. Use PATHEXT from the explicit consumer environment.
    names = tool_names(env)
    directories = [home] if os.name == "nt" else []
    for directory in env["PATH"].split(os.pathsep):
        path = Path(directory.strip('"')) if directory else home
        directories.append(path if path.is_absolute() else home / path)
    resolved_tools = {}
    for name in sorted(names):
        resolved_tools[name] = next(
            (
                str(directory / name)
                for directory in directories
                if (directory / name).is_file()
                and (os.name == "nt" or os.access(directory / name, os.X_OK))
            ),
            None,
        )
    if any(resolved_tools.values()):
        return {
            "status": "fail",
            "reason": "Node/Bun still resolvable",
            "resolved_tools": resolved_tools,
        }
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
    expected = json.loads(
        (root / "fixtures/expected-output.json").read_text(encoding="utf-8")
    )
    destination = home / ".spike-target"
    tree_matches = installed_tree_matches(root=destination, expected=expected)
    try:
        stdout_matches = json.loads(result["stdout"]) == expected
    except (ValueError, TypeError):
        stdout_matches = False
    try:
        # lstat short-circuits before reading a replacement symlink/directory.
        cache_blocked = stat.S_ISREG(cache.lstat().st_mode)
        if cache_blocked:
            with cache.open("rb") as stream:
                cache_blocked = stream.read(len(blocker) + 1) == blocker
    except OSError:
        cache_blocked = False
    other_home_files = [
        p.relative_to(home).as_posix()
        for p in home.rglob("*")
        if p != cache
        and destination not in p.parents
        and (p.is_symlink() or p.is_file())
    ]
    return {
        "status": (
            "pass"
            if result["exit"] == 0
            and stdout_matches
            and tree_matches
            and not other_home_files
            and cache_blocked
            else "fail"
        ),
        "seconds": result["seconds"],
        "exit": result["exit"],
        "PATH": env["PATH"],
        "resolved_tools": resolved_tools,
        "installed_tree_matches": tree_matches,
        "cache_directory_blocked": cache_blocked,
        "other_HOME_files": other_home_files,
        "cache_scope": (
            "HOME only; writes elsewhere and read-only runtime trees unverified"
        ),
    }
