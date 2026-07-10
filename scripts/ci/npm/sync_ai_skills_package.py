#!/usr/bin/env python3
"""Synchronize generated data and version for the ai-skills npm package.

Usage:
    uv run python scripts/ci/npm/sync_ai_skills_package.py
    uv run python scripts/ci/npm/sync_ai_skills_package.py --version v1.2.3
    uv run python scripts/ci/npm/sync_ai_skills_package.py --check
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = PROJECT_ROOT / "npm" / "ai-skills"
DATA_ROOT = PACKAGE_ROOT / "data"
PACKAGE_MANIFEST = PACKAGE_ROOT / "package.json"
SOURCE_DATA = {
    PROJECT_ROOT / "vendors.yaml": DATA_ROOT / "vendors.yaml",
    PROJECT_ROOT / "bundles.yaml": DATA_ROOT / "bundles.yaml",
    PROJECT_ROOT / "NOTICE.md": PACKAGE_ROOT / "NOTICE.md",
}


def normalize_version(raw_version: str) -> str:
    """Return an npm version without a leading tag prefix.

    Args:
        raw_version: Semver string, optionally prefixed with ``v``.

    Returns:
        The normalized semver string.
    """
    return raw_version.removeprefix("v")


def rendered_files(version: str) -> dict[Path, str]:
    """Render every generated package artifact from repository sources.

    Args:
        version: Version to write into the package manifest.

    Returns:
        Mapping of package paths to their generated content.
    """
    manifest = json.loads(PACKAGE_MANIFEST.read_text(encoding="utf-8"))
    manifest["version"] = version
    files = {
        destination: source.read_text(encoding="utf-8")
        for source, destination in SOURCE_DATA.items()
    }
    files[PACKAGE_ROOT / "NOTICE.md"] = files[PACKAGE_ROOT / "NOTICE.md"].replace(
        "`vendors.yaml`",
        "`data/vendors.yaml`",
    )
    files[DATA_ROOT / "vendors.json"] = (
        json.dumps(
            yaml.safe_load((PROJECT_ROOT / "vendors.yaml").read_text(encoding="utf-8")),
            indent=2,
        )
        + "\n"
    )
    files[DATA_ROOT / "bundles.json"] = (
        json.dumps(
            yaml.safe_load((PROJECT_ROOT / "bundles.yaml").read_text(encoding="utf-8")),
            indent=2,
        )
        + "\n"
    )
    for index_path in sorted((PROJECT_ROOT / "vendor-indexes").glob("*.json")):
        files[DATA_ROOT / "vendor-indexes" / index_path.name] = index_path.read_text(
            encoding="utf-8",
        )
    files[PACKAGE_MANIFEST] = json.dumps(manifest, indent=2) + "\n"
    return files


def write_rendered(files: dict[Path, str]) -> None:
    """Write changed generated files to the package directory.

    Args:
        files: Generated content by absolute destination path.
    """
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
            print(f"Wrote {path.relative_to(PROJECT_ROOT)}")


def check_rendered(files: dict[Path, str]) -> int:
    """Report generated package files that differ from source data.

    Args:
        files: Expected generated content by absolute destination path.

    Returns:
        Zero when all artifacts are synchronized, otherwise one.
    """
    has_drift = False
    for path, expected in files.items():
        actual = path.read_text(encoding="utf-8") if path.is_file() else ""
        if actual == expected:
            continue
        has_drift = True
        sys.stderr.writelines(
            difflib.unified_diff(
                actual.splitlines(keepends=True),
                expected.splitlines(keepends=True),
                fromfile=str(path.relative_to(PROJECT_ROOT)),
                tofile="generated",
            ),
        )
    return int(has_drift)


def main(argv: list[str] | None = None) -> int:
    """Synchronize package artifacts or verify they are current.

    Args:
        argv: Optional command line arguments.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        default="0.0.0-dev",
        help="npm version to inject, optionally prefixed with v",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify generated artifacts without writing them",
    )
    args: Any = parser.parse_args(argv)
    files = rendered_files(version=normalize_version(args.version))
    if args.check:
        return check_rendered(files)
    write_rendered(files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
