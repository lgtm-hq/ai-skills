#!/usr/bin/env python3
"""Prove explicit OS-level network denial; a timeout alone is inconclusive."""

from __future__ import annotations

import errno
import json
import socket


def main() -> int:
    """Probe public IPv4 and IPv6 with a credential-free bundled interpreter.

    Returns:
        Zero only if both connections fail with an explicit permission/route denial.
    """
    outcomes = []
    for family, address in [
        (socket.AF_INET, "1.1.1.1"),
        (socket.AF_INET6, "2606:4700:4700::1111"),
    ]:
        with socket.socket(family=family) as connection:
            connection.settimeout(2)
            try:
                connection.connect((address, 443))
                outcomes.append(
                    {
                        "address": address,
                        "denied": False,
                        "error": "connection succeeded",
                    }
                )
            except OSError as error:
                outcomes.append(
                    {
                        "address": address,
                        "denied": error.errno
                        in {
                            errno.EPERM,
                            errno.EACCES,
                            errno.ENETUNREACH,
                            errno.EAFNOSUPPORT,
                            errno.EADDRNOTAVAIL,
                            10013,
                            10051,
                            10047,
                            10049,
                        },
                        "errno": error.errno,
                        "error": str(error),
                    }
                )
    print(json.dumps(outcomes))
    return 0 if all(item["denied"] for item in outcomes) else 2


if __name__ == "__main__":
    raise SystemExit(main())
