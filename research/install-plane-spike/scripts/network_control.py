#!/usr/bin/env python3
"""Observe connectivity; only a matched positive control can prove isolation."""

from __future__ import annotations

import errno
import json
import socket
from typing import Any

TARGET = "1.1.1.1"
PORT = 443


def probe() -> list[dict[str, Any]]:
    """Probe a fixed IPv4 endpoint and collect informational IPv6 observations.

    Returns:
        Raw connection outcomes; timeouts are always inconclusive.
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
        try:
            with socket.socket(family=family) as connection:
                connection.settimeout(2)
                connection.connect((address, PORT))
            item["outcome"] = "connected"
        except OSError as error:
            item.update(errno=error.errno, error=str(error))
            item["outcome"] = (
                "explicit-denial"
                if error.errno
                in {
                    errno.EPERM,
                    errno.EACCES,
                    errno.ENETUNREACH,
                    errno.EHOSTUNREACH,
                    10013,
                    10051,
                    10065,
                }
                else "inconclusive"
            )
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
