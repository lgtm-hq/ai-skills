#!/usr/bin/env python3
"""Record native quarantine/security-tool outputs without inferring EDR approval."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Any

from common import command, run_payload, runtime


def measure_quarantine(*, root: Path, variant: str, home: Path) -> dict[str, Any]:
    """Mark a disposable payload and measure available platform controls.

    Args:
        root: Disposable copy of the variant payload.
        variant: ts or py.
        home: Disposable runtime HOME.

    Returns:
        Raw commands and narrow execution/assessment observations.
    """
    records: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "status": "unverified",
        "commands": records,
        "edr": "unverified: third-party EDR and org policy unavailable",
    }
    binary = runtime(root=root, variant=variant)[0]
    if platform.system() == "Darwin":
        required = [shutil.which(name) for name in ("xattr", "spctl", "codesign")]
        if any(path is None for path in required):
            result["reason"] = "xattr, spctl or codesign absent on this runner"
            return result
        mark = command(
            argv=[
                str(required[0]),
                "-r",
                "-w",
                "com.apple.quarantine",
                "0083;67240000;InstallPlaneSpike;",
                str(root),
            ],
            records=records,
        )
        read = command(
            argv=[str(required[0]), "-p", "com.apple.quarantine", binary],
            records=records,
        )
        command(
            argv=[
                str(required[1]),
                "--assess",
                "--type",
                "execute",
                "--verbose=4",
                binary,
            ],
            records=records,
        )
        command(
            argv=[str(required[2]), "--display", "--verbose=4", binary], records=records
        )
        command(
            argv=[
                str(required[2]),
                "--verify",
                "--deep",
                "--strict",
                "--verbose=4",
                binary,
            ],
            records=records,
        )
        if mark["exit"] != 0 or read["exit"] != 0:
            result["reason"] = "quarantine attribute could not be set/read"
            return result
        result.update(
            status="measured",
            execution=run_payload(
                root=root, variant=variant, home=home, records=records
            ),
        )
        result["signing"] = (
            "Use spctl/codesign output; CLI launch does not establish "
            "Finder/Gatekeeper or notarization requirements. Notarization unverified."
        )
    elif os.name == "nt":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            result["reason"] = (
                "PowerShell unavailable for Mark-of-the-Web and signature inspection"
            )
            return result
        literal = "'" + binary.replace("'", "''") + "'"
        mark = command(
            argv=[
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "$ErrorActionPreference='Stop'; Set-Content -LiteralPath "
                    f"{literal} "
                    '-Stream Zone.Identifier -Value "[ZoneTransfer]`nZoneId=3"; '
                    f"Get-Content -LiteralPath {literal} -Stream Zone.Identifier"
                ),
            ],
            records=records,
        )
        command(
            argv=[
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"Get-AuthenticodeSignature -LiteralPath {literal} | Format-List *",
            ],
            records=records,
        )
        defender_dir = (
            Path(os.environ.get("ProgramData", "C:/ProgramData"))
            / "Microsoft/Windows Defender/Platform"
        )
        scanners = sorted(defender_dir.glob("*/MpCmdRun.exe"), reverse=True)
        fallback = (
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "Windows Defender/MpCmdRun.exe"
        )
        scanner = scanners[0] if scanners else fallback
        if scanner.is_file():
            scan = command(
                argv=[str(scanner), "-Scan", "-ScanType", "3", "-File", str(root)],
                records=records,
                timeout=300,
            )
            result["defender"] = "pass" if scan["exit"] == 0 else "fail"
        else:
            result["defender"] = (
                f"unverified: no MpCmdRun.exe under {defender_dir} or {fallback}"
            )
        if mark["exit"] != 0:
            result["reason"] = "Mark-of-the-Web write/read failed (see exact output)"
            return result
        result.update(
            status="measured",
            execution=run_payload(
                root=root, variant=variant, home=home, records=records
            ),
        )
        result["signing"] = (
            "Authenticode status recorded; SmartScreen interactive reputation "
            "and corporate signing requirements unverified."
        )
    else:
        result["reason"] = (
            "Linux has no macOS quarantine or Windows Defender/MOTW; "
            "third-party EDR unavailable"
        )
    return result
