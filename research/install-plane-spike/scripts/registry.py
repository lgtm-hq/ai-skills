#!/usr/bin/env python3
"""Measure a private-only Verdaccio transport with optional platform packages."""

from __future__ import annotations

import http.client
import json
import os
import secrets
import shutil
import socket
import subprocess  # nosec B404 - pinned local test server, explicit argv
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from common import SETTINGS, SPIKE, command, run_payload, target, write_json


def package(*, path: Path, name: str, variant: str, platform_package: bool) -> None:
    """Write a scripts-free wrapper or platform package manifest.

    Args:
        path: Temporary package root.
        name: Scoped package name.
        variant: ts or py.
        platform_package: Whether this is a platform payload rather than wrapper.
    """
    manifest: dict[str, Any] = {"name": name, "version": "0.0.1", "private": False}
    system, cpu = target().split("-")
    if platform_package:
        manifest.update(
            os=["win32" if system == "windows" else system],
            cpu=[cpu],
            files=["payload"],
        )
    else:
        manifest["optionalDependencies"] = {
            f"@spike/{variant}-{item}": "0.0.1" for item in SETTINGS["targets"]
        }
    write_json(path=path / "package.json", value=manifest)


def measure_registry(*, build: Path, work: Path) -> dict[str, Any]:
    """Publish both payloads locally, install with scripts disabled, then execute.

    Args:
        build: Native build directory.
        work: Disposable registry and client working directory.

    Returns:
        Per-variant evidence, plus the full Verdaccio command/output record.
    """
    records: list[dict[str, Any]] = []
    results: dict[str, Any] = {}
    bun = shutil.which("bun")
    bunx = shutil.which("bunx")
    if bun is None or bunx is None:
        return {
            v: {"status": "unverified", "reason": "Bun/bunx absent from setup PATH"}
            for v in ("ts", "py")
        }
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    config = work / "verdaccio.yaml"
    # No uplinks means a missing platform package cannot fall back to public npm.
    config.write_text(
        f"storage: {json.dumps(str(work / 'storage'))}\n"
        f"max_body_size: {SETTINGS['registry_max_body_size']}\n"
        "auth:\n  htpasswd:\n    file: ./htpasswd\nuplinks: {}\n"
        "packages:\n  '**':\n    access: $all\n    publish: $all\n    unpublish: $all\n"
        "log: {type: stdout, format: pretty, level: http}\n",
    )
    argv = [
        bunx,
        "--bun",
        "--no-install",
        f"verdaccio@{SETTINGS['verdaccio']}",
        "--config",
        str(config),
        "--listen",
        f"127.0.0.1:{port}",
    ]
    stdout_path, stderr_path = work / "verdaccio.stdout", work / "verdaccio.stderr"
    started = time.perf_counter()
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        try:
            server = subprocess.Popen(  # nosec B603 - pinned cached Verdaccio, no shell
                args=argv,
                cwd=SPIKE / "ts",
                stdout=stdout,
                stderr=stderr,
            )
        except OSError as error:
            return {
                v: {"status": "unverified", "reason": str(error), "argv": argv}
                for v in ("ts", "py")
            }
        try:
            ready = False
            for _ in range(150):
                try:
                    with closing(
                        http.client.HTTPConnection(
                            host="127.0.0.1",
                            port=port,
                            timeout=1,
                        )
                    ) as connection:
                        connection.request(method="GET", url="/-/ping")
                        response = connection.getresponse()
                        response.read()
                        ready = response.status == 200
                except OSError:
                    pass
                if ready or server.poll() is not None:
                    break
                time.sleep(0.1)
            token = ""
            if ready:
                with closing(
                    http.client.HTTPConnection(
                        host="127.0.0.1",
                        port=port,
                        timeout=10,
                    )
                ) as connection:
                    connection.request(
                        method="PUT",
                        url="/-/user/org.couchdb.user:spike",
                        body=json.dumps(
                            {
                                "name": "spike",
                                "password": secrets.token_urlsafe(24),
                            }
                        ),
                        headers={"Content-Type": "application/json"},
                    )
                    token = json.loads(connection.getresponse().read())["token"]
            for variant in ("ts", "py"):
                entries: list[dict[str, Any]] = []
                results[variant] = {
                    "status": "fail",
                    "registry": url,
                    "uplinks": {},
                    "configuration": config.read_text(),
                    "commands": entries,
                }
                if not ready:
                    results[variant][
                        "reason"
                    ] = "cached Verdaccio did not become ready; see server output"
                    continue
                native_name = f"@spike/{variant}-{target()}"
                platform_dir = work / f"package-{variant}"
                platform_dir.mkdir()
                shutil.copytree(src=build / variant, dst=platform_dir / "payload")
                package(
                    path=platform_dir,
                    name=native_name,
                    variant=variant,
                    platform_package=True,
                )
                wrapper = work / f"wrapper-{variant}"
                wrapper.mkdir()
                package(
                    path=wrapper,
                    name=f"@spike/{variant}",
                    variant=variant,
                    platform_package=False,
                )
                # Incompatible empty packages let all optional refs resolve locally.
                publish_dirs = [platform_dir, wrapper]
                for item in SETTINGS["targets"]:
                    if item == target():
                        continue
                    other = work / f"{variant}-{item}"
                    other.mkdir()
                    other_system, other_cpu = item.split("-")
                    write_json(
                        path=other / "package.json",
                        value={
                            "name": f"@spike/{variant}-{item}",
                            "version": "0.0.1",
                            "os": [
                                "win32" if other_system == "windows" else other_system
                            ],
                            "cpu": [other_cpu],
                        },
                    )
                    publish_dirs.insert(0, other)
                env = {
                    key: value
                    for key, value in os.environ.items()
                    if key not in {"PYTHONPATH", "NODE_AUTH_TOKEN", "NPM_CONFIG_TOKEN"}
                }
                env["NPM_CONFIG_REGISTRY"] = url
                # Synthetic local credentials only; never a user or GitHub token.
                env["NPM_CONFIG_TOKEN"] = token
                failed = False
                for directory in publish_dirs:
                    record = command(
                        argv=[bun, "publish", "--registry", url, "--ignore-scripts"],
                        cwd=directory,
                        env=env,
                        records=entries,
                        timeout=300,
                    )
                    if record["exit"] != 0:
                        failed = True
                        break
                if failed:
                    results[variant]["reason"] = "local publication failed"
                    continue
                client = work / f"client-{variant}"
                client.mkdir()
                (client / ".npmrc").write_text(f"registry={url}\nignore-scripts=true\n")
                write_json(
                    path=client / "package.json",
                    value={
                        "private": True,
                        "dependencies": {f"@spike/{variant}": "0.0.1"},
                    },
                )
                # Install from an empty cache, with no registry authentication.
                del env["NPM_CONFIG_TOKEN"]
                env.update(
                    BUN_INSTALL_CACHE_DIR=str(client / "cache"),
                    BUN_CONFIG_NO_CLEAR_TERMINAL="1",
                )
                installed = command(
                    argv=[bun, "install", "--ignore-scripts", "--registry", url],
                    cwd=client,
                    env=env,
                    records=entries,
                    timeout=300,
                )
                payload = client / "node_modules" / native_name / "payload"
                if installed["exit"] != 0 or not payload.is_dir():
                    results[variant][
                        "reason"
                    ] = "private install failed or optional payload silently omitted"
                    continue
                with tempfile.TemporaryDirectory(
                    prefix="registry-runtime-"
                ) as temporary:
                    observed = run_payload(
                        root=payload,
                        variant=variant,
                        home=Path(temporary),
                        records=entries,
                    )
                results[variant].update(status=observed["status"], observation=observed)
                results[variant]["limitation"] = (
                    "registry-only configuration/no uplinks; no OS firewall around "
                    "the client; incompatible packages are empty stand-ins"
                )
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
    server_record = {
        "argv": argv,
        "cwd": str(SPIKE / "ts"),
        "exit": server.returncode,
        "stdout": stdout_path.read_text(errors="replace"),
        "stderr": stderr_path.read_text(errors="replace"),
        "seconds": time.perf_counter() - started,
        "termination": "intentional server shutdown",
    }
    records.append(server_record)
    print(json.dumps(server_record), flush=True)
    results["server"] = records
    return results
