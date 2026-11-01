#!/usr/bin/env python3
"""Measure scripts-free npm wrapper installs via an isolated loopback registry."""

from __future__ import annotations

import http.client
import json
import os
import secrets
import shutil
import socket
import subprocess  # nosec B404 - pinned local test server, explicit argv
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from common import SETTINGS, SPIKE, command, write_json
from packages import client_env, install_client, prepare_packages


def redact(*, value: object, sensitive: list[str]) -> Any:
    """Remove credentials from structured responses and raw server/client output.

    Args:
        value: Evidence to sanitize before persistence or display.
        sensitive: Ephemeral account credentials, never inherited user credentials.

    Returns:
        Evidence with credential fields and known secret values removed.
    """
    if isinstance(value, dict):
        return {
            key: (
                "[redacted]"
                if any(
                    word in key.lower()
                    for word in ("token", "password", "authorization", "_auth")
                )
                else redact(value=item, sensitive=sensitive)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(value=item, sensitive=sensitive) for item in value]
    if isinstance(value, str):
        for secret in sensitive:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


def account(
    *, port: int, password: str, records: list[dict[str, Any]], sensitive: list[str]
) -> str:
    """Create an ephemeral registry account, validating status, JSON and token.

    Args:
        port: Loopback stand-in port.
        password: Random test-only password.
        records: Sanitized HTTP evidence, without raw credential response bodies.
        sensitive: Redaction set extended even for rejected credential responses.

    Returns:
        Validated temporary publication token (never logged).

    Raises:
        ValueError: For rejected status, invalid JSON or missing/invalid token.
        OSError: On connection/read timeouts.
        http.client.HTTPException: On invalid HTTP responses.
    """
    record: dict[str, Any] = {"operation": "create disposable loopback account"}
    records.append(record)
    with closing(
        http.client.HTTPConnection(host="127.0.0.1", port=port, timeout=10)
    ) as connection:
        connection.request(
            method="PUT",
            url="/-/user/org.couchdb.user:spike",
            body=json.dumps({"name": "spike", "password": password}),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        record["status"] = response.status
        raw = response.read()
        record["body_bytes"] = len(raw)
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError) as error:
            record["error"] = (
                "Unreadable JSON; account body withheld to protect credentials"
            )
            raise ValueError(record["error"]) from error
        token = body.get("token") if isinstance(body, dict) else None
        if isinstance(token, str) and token.strip():
            sensitive.append(token)
        record["response"] = (
            redact(value=body, sensitive=sensitive)
            if isinstance(body, dict)
            else {"type": type(body).__name__}
        )
        if response.status not in {200, 201}:
            raise ValueError("registry rejected account creation")
        if (
            not isinstance(token, str)
            or not token
            or not token.isascii()
            or any(c.isspace() for c in token)
        ):
            raise ValueError("missing or invalid registry token")
        return token


def measure_registry(*, build: Path, work: Path) -> dict[str, Any]:
    """Retain failures and server output while independent scenarios continue.

    Args:
        build: Native payloads to publish and compare with installed bytes.
        work: Disposable stand-in directory.

    Returns:
        Bun and npm client evidence per variant, plus sanitized server/HTTP logs.
    """
    records: list[dict[str, Any]] = []
    results: dict[str, Any] = {
        variant: {
            "status": "fail",
            "commands": [],
            "limitation": (
                "no uplinks; registry-only configuration, not an OS firewall; "
                "incompatible platform packages are empty stand-ins"
            ),
        }
        for variant in ("ts", "py")
    }
    bun = shutil.which("bun")
    if bun is None:
        return {
            v: {"status": "unverified", "reason": "Bun absent from setup PATH"}
            for v in results
        }
    server = None
    argv: list[str] = []
    sensitive = [secrets.token_urlsafe(24)]
    stdout_path, stderr_path = work / "verdaccio.stdout", work / "verdaccio.stderr"
    started = time.perf_counter()
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        config = work / "verdaccio.yaml"
        config.write_text(
            f"storage: {json.dumps(str(work / 'storage'))}\n"
            f"max_body_size: {SETTINGS['registry_max_body_size']}\n"
            "auth:\n  htpasswd:\n    file: ./htpasswd\nuplinks: {}\n"
            "packages:\n  '**':\n    access: $all\n    publish: $authenticated\n"
            "log: {type: stdout, format: pretty, level: http}\n",
            encoding="utf-8",
        )
        argv = [
            bun,
            "x",
            "--bun",
            "--no-install",
            f"verdaccio@{SETTINGS['verdaccio']}",
            "--config",
            str(config),
            "--listen",
            f"127.0.0.1:{port}",
        ]
        server_env = client_env(client=work / "server-env", registry=url)
        # Keep Bun's pre-primed bun-x cache for server startup only.
        # This contains tooling, never a measured install client's package cache.
        server_env["BUN_INSTALL_CACHE_DIR"] = os.environ.get(
            "BUN_INSTALL_CACHE_DIR", str(Path.home() / ".bun/install/cache")
        )
        with (
            stdout_path.open("w", encoding="utf-8") as stdout,
            stderr_path.open("w", encoding="utf-8") as stderr,
        ):
            server = subprocess.Popen(  # nosec B603 - pinned cached Verdaccio, no shell
                args=argv,
                cwd=SPIKE / "ts",
                env=server_env,
                stdout=stdout,
                stderr=stderr,
            )
        ready = False
        readiness: dict[str, Any] = {"operation": "registry readiness"}
        records.append(readiness)
        for _ in range(150):
            try:
                with closing(
                    http.client.HTTPConnection(host="127.0.0.1", port=port, timeout=1)
                ) as connection:
                    connection.request(method="GET", url="/-/ping")
                    response = connection.getresponse()
                    response.read()
                    readiness["status"] = response.status
                    ready = response.status == 200
            except (OSError, http.client.HTTPException) as error:
                readiness["error"] = type(error).__name__
            if ready or server.poll() is not None:
                break
            time.sleep(0.1)
        if not ready:
            raise ValueError("cached registry readiness failed or timed out")
        token = account(
            port=port, password=sensitive[0], records=records, sensitive=sensitive
        )
        for variant in ("ts", "py"):
            entries = results[variant]["commands"]
            results[variant].update(
                registry=url,
                uplinks={},
                configuration=config.read_text(encoding="utf-8"),
            )
            try:
                directories = prepare_packages(
                    build=build, work=work / variant, variant=variant
                )
                publisher = client_env(
                    client=work / f"publisher-{variant}", registry=url
                )
                publisher["NPM_CONFIG_TOKEN"] = token
                for directory in directories:
                    record = command(
                        argv=[bun, "publish", "--registry", url, "--ignore-scripts"],
                        cwd=directory,
                        env=publisher,
                        records=entries,
                        timeout=300,
                        redactions=tuple(sensitive),
                    )
                    if record["exit"] != 0:
                        raise ValueError("local publication failed")
                clients: dict[str, dict[str, Any]] = {}
                results[variant]["clients"] = clients
                for tool in ("bun", "npm"):
                    clients[tool] = install_client(
                        build=build,
                        client=work / f"client-{variant}-{tool}",
                        variant=variant,
                        tool=tool,
                        dependency="0.0.1",
                        registry=url,
                    )
                results[variant]["status"] = (
                    "pass"
                    if all(item["status"] == "pass" for item in clients.values())
                    else "fail"
                )
            except (OSError, ValueError) as error:
                results[variant]["reason"] = str(
                    redact(value=str(error), sensitive=sensitive)
                )
    except (OSError, ValueError, http.client.HTTPException) as error:
        # Never include exception request/body data: timeouts and malformed HTTP
        # are failure evidence, not a reason to lose offline/quarantine results.
        for variant in ("ts", "py"):
            results[variant][
                "reason"
            ] = f"registry collection failed: {type(error).__name__}"
        records.append(
            {
                "error": type(error).__name__,
                "detail": str(redact(value=str(error), sensitive=sensitive)),
            }
        )
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        server_record = {
            "argv": argv,
            "exit": server.returncode if server else None,
            "stdout": (
                stdout_path.read_text(encoding="utf-8", errors="replace")
                if stdout_path.exists()
                else ""
            ),
            "stderr": (
                stderr_path.read_text(encoding="utf-8", errors="replace")
                if stderr_path.exists()
                else ""
            ),
            "seconds": time.perf_counter() - started,
            "termination": "intentional server shutdown",
        }
        records.append(redact(value=server_record, sensitive=sensitive))
        results["server"] = records
    sanitized: dict[str, Any] = redact(value=results, sensitive=sensitive)
    write_json(path=work / "registry-evidence.json", value=sanitized)
    return sanitized
