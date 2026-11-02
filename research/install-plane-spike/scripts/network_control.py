#!/usr/bin/env python3
"""Observe connectivity; only a matched positive control can prove isolation."""

from __future__ import annotations

import errno
import json
import socket
import sys
from pathlib import Path
from sys import exception
from typing import Any

ENDPOINT = json.loads(
    (Path(__file__).resolve().parents[1] / "network-control.json").read_bytes()
)
TARGET = ENDPOINT["address"]
PORT = ENDPOINT["port"]


def socket_error(*, error: OSError, stage: str) -> dict[str, Any]:
    """Retain the raw OS failure and the lifecycle operation that raised it."""
    raw = {"stage": stage, "errno": error.errno, "error": str(error)}
    if (winerror := getattr(error, "winerror", None)) is not None:
        raw["winerror"] = winerror
    return raw


def probe() -> list[dict[str, Any]]:
    """Probe a fixed IPv4 endpoint and collect informational IPv6 observations.

    Returns:
        Raw connection outcomes; unreachable, refusal and timeouts are inconclusive.
    """
    outcomes = []
    for family, address in [
        (socket.AF_INET, TARGET),
        (socket.AF_INET6, "2606:4700:4700::1111"),
    ]:
        item: dict[str, Any] = {
            "address": address,
            "port": PORT,
            "informational": family == socket.AF_INET6,
        }
        connection = None
        stage = "create"
        try:
            connection = socket.socket(family=family)
            stage = "settimeout"
            connection.settimeout(2)
            stage = "connect"
            connection.connect((address, PORT))
            item["outcome"] = "connected"
        except OSError as error:
            item.update(socket_error(error=error, stage=stage))
            winerror = getattr(error, "winerror", None)
            # A lost route is not access denial, even after a connected baseline.
            # Windows errno is translated; require the actual Winsock WSAEACCES.
            denied = (
                winerror == 10013
                if sys.platform == "win32"
                else error.errno in {errno.EPERM, errno.EACCES}
            )
            item["outcome"] = (
                "explicit-denial" if stage == "connect" and denied else "inconclusive"
            )
        finally:
            if connection is not None:
                original = exception()
                try:
                    connection.close()
                except OSError as error:
                    if original is not None:
                        original.add_note(f"Socket close also failed: {error}")
                    raw = socket_error(error=error, stage="close")
                    item["cleanup_error"] = raw
                    item["outcome_before_cleanup"] = item.get("outcome", "inconclusive")
                    if "error" not in item:
                        item.update(raw)
                    item["outcome"] = "inconclusive"
        outcomes.append(item)
    return outcomes


def proven_denial(*, control: dict[str, Any], restricted: dict[str, Any]) -> bool:
    """Require successful IPv4 before explicit denial of the identical endpoint.

    Args:
        control: Unrestricted probe command record from this host.
        restricted: Probe command record under the measured restriction.

    Returns:
        Whether this pair establishes denial; IPv6 cannot establish it.
    """
    try:
        before = json.loads(control["stdout"])[0]
        after = json.loads(restricted["stdout"])[0]
        return bool(
            control["exit"] == 0
            and restricted["exit"] == 0
            and before["address"] == after["address"] == TARGET
            and before["port"] == after["port"] == PORT
            and before["outcome"] == "connected"
            and after["outcome"] == "explicit-denial"
        )
    except (ValueError, KeyError, TypeError, IndexError):
        return False


if __name__ == "__main__":
    print(json.dumps(probe()))
