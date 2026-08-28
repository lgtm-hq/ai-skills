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
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = PROJECT_ROOT / "npm" / "ai-skills"
DATA_ROOT = PACKAGE_ROOT / "data"
PACKAGE_MANIFEST = PACKAGE_ROOT / "package.json"
PLUGINS_BAKED_NAME = "plugins-baked"
SOURCE_DATA = {
    PROJECT_ROOT / "vendors.yaml": DATA_ROOT / "vendors.yaml",
    PROJECT_ROOT / "bundles.yaml": DATA_ROOT / "bundles.yaml",
    PROJECT_ROOT / "NOTICE.md": PACKAGE_ROOT / "NOTICE.md",
}
SEMVER_PATTERN = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|[0-9A-Za-z-]+)(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]+))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$",
)


def normalize_version(raw_version: str) -> str:
    """Validate and return an npm version without a leading tag prefix.

    Args:
        raw_version: Semver string, optionally prefixed with ``v``.

    Returns:
        The normalized semver string.

    Raises:
        ValueError: If the version is not valid semantic versioning.
    """
    version = raw_version.removeprefix("v")
    if not SEMVER_PATTERN.fullmatch(version):
        msg = f"Invalid npm semver version: {raw_version}"
        raise ValueError(msg)
    return version


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


def plugins_baked_source() -> Path:
    """Return the repository bake output directory.

    Returns:
        Absolute ``plugins-baked`` path at the repository root.
    """
    return PROJECT_ROOT / PLUGINS_BAKED_NAME


def plugins_baked_destination() -> Path:
    """Return the npm package copy of bake output.

    Returns:
        Absolute ``data/plugins-baked`` path inside the gateway package.
    """
    return DATA_ROOT / PLUGINS_BAKED_NAME


def _tree_file_map(*, root: Path) -> dict[str, Path]:
    """Index regular files under ``root`` by POSIX relative path.

    Args:
        root: Directory to walk.

    Returns:
        Relative path to absolute file path.
    """
    files: dict[str, Path] = {}
    if not root.is_dir():
        return files
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        files[path.relative_to(root).as_posix()] = path
    return files


def check_plugins_baked() -> int:
    """Report when the packaged bake tree drifts from repository output.

    Returns:
        Zero when the trees match (including both absent), otherwise one.
    """
    source = plugins_baked_source()
    dest = plugins_baked_destination()
    if not source.is_dir() and not dest.exists():
        return 0
    if not source.is_dir() or not dest.is_dir():
        dest_rel = dest.relative_to(PROJECT_ROOT)
        sys.stderr.write(f"{dest_rel}: plugins-baked tree is out of date\n")
        return 1
    expected = _tree_file_map(root=source)
    actual = _tree_file_map(root=dest)
    if expected.keys() != actual.keys():
        missing = sorted(expected.keys() - actual.keys())
        extra = sorted(actual.keys() - expected.keys())
        dest_rel = dest.relative_to(PROJECT_ROOT)
        if missing:
            sys.stderr.write(f"{dest_rel}: missing {missing[0]}\n")
        if extra:
            sys.stderr.write(f"{dest_rel}: extra {extra[0]}\n")
        return 1
    for rel_path, expected_path in expected.items():
        if expected_path.read_bytes() != actual[rel_path].read_bytes():
            sys.stderr.write(
                f"{dest.relative_to(PROJECT_ROOT) / rel_path}: "
                "plugins-baked file is out of date\n",
            )
            return 1
    return 0


def write_plugins_baked() -> None:
    """Copy repository bake output into the npm package data tree."""
    source = plugins_baked_source()
    dest = plugins_baked_destination()
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    elif dest.is_dir():
        shutil.rmtree(dest)
    if not source.is_dir():
        return
    shutil.copytree(src=source, dst=dest, symlinks=False)
    print(f"Wrote {dest.relative_to(PROJECT_ROOT)}")


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
        return int(bool(check_rendered(files) or check_plugins_baked()))
    write_rendered(files)
    write_plugins_baked()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
