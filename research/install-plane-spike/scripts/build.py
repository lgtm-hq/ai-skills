#!/usr/bin/env python3
"""Build only this runner's native payloads; setup may use the network."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tarfile
from pathlib import Path

from common import SETTINGS, SPIKE, checked, runtime, target, write_json


def main() -> None:
    """Build A with Bun and B by copying uv's full standalone CPython tree."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--installed-python",
        action="store_true",
        help="never download a Python locally",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    records = []
    source_hashes = {
        path.relative_to(SPIKE).as_posix(): (
            hashlib.sha256(path.read_bytes()).hexdigest()
        )
        for path in SPIKE.rglob("*")
        if path.is_file()
        and not {"node_modules", "__pycache__"}.intersection(path.parts)
    }
    try:
        checked(argv=["bun", "--version"], records=records)
        checked(argv=["uv", "--version"], records=records)
        checked(
            argv=[sys.executable, str(SPIKE / "scripts/fixture.py"), "--check"],
            records=records,
        )
        checked(
            argv=["bun", "install", "--frozen-lockfile"],
            records=records,
            cwd=SPIKE / "ts",
        )
        checked(argv=["bun", "test", "--coverage"], records=records, cwd=SPIKE / "ts")
        checked(
            argv=["bunx", "--no-install", "tsc", "--noEmit"],
            records=records,
            cwd=SPIKE / "ts",
        )
        if not args.installed_python:
            checked(
                argv=["uv", "python", "install", SETTINGS["python"]], records=records
            )
        interpreter = Path(
            checked(
                argv=[
                    "uv",
                    "python",
                    "find",
                    "--system",
                    "--managed-python",
                    SETTINGS["python"],
                ],
                records=records,
            ).strip()
        ).resolve()
        # uv-managed Python uses python-build-standalone install_only distributions.
        python_root = (
            interpreter.parent if sys.platform == "win32" else interpreter.parent.parent
        )
        checked(
            argv=[
                str(interpreter),
                "-I",
                "-c",
                (
                    "import sys,platform; print(sys.version); print(sys.prefix); "
                    "print(platform.platform())"
                ),
            ],
            records=records,
        )
        for variant in ("ts", "py"):
            root = output / variant
            root.mkdir()
            shutil.copytree(src=SPIKE / "fixtures", dst=root / "fixtures")
            if variant == "ts":
                binary = root / ("spike.exe" if sys.platform == "win32" else "spike")
                checked(
                    argv=[
                        "bun",
                        "build",
                        "--compile",
                        f"--target=bun-{target()}",
                        str(SPIKE / "ts/prototype.ts"),
                        "--outfile",
                        str(binary),
                    ],
                    records=records,
                )
            else:
                # npm pack omits links. Dereference them; keep stdlib and native libs.
                shutil.copytree(src=python_root, dst=root / "runtime", symlinks=False)
                shutil.copy2(src=SPIKE / "py/prototype.py", dst=root / "prototype.py")
            with tarfile.open(name=output / f"{variant}.tgz", mode="w:gz") as archive:
                archive.add(name=root, arcname="payload")
            if variant == "py":
                checked(
                    argv=[runtime(root=root, variant=variant)[0], "--version"],
                    records=records,
                )
        # Prime Verdaccio now. The scenario uses --no-install and has no uplinks.
        checked(
            argv=["bunx", "--bun", f"verdaccio@{SETTINGS['verdaccio']}", "--version"],
            records=records,
        )
    finally:
        write_json(
            path=output / "build.json",
            value={
                "target": target(),
                "source_sha256": source_hashes,
                "commands": records,
            },
        )


if __name__ == "__main__":
    main()
