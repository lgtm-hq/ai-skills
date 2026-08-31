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
PLUGINS_BAKED_DIRNAME = "plugins-baked"


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


def baked_plugin_source() -> Path:
    """Return the repository ``plugins-baked/`` directory.

    Returns:
        Absolute path of the local bake output (may be absent).
    """
    return PROJECT_ROOT / PLUGINS_BAKED_DIRNAME


def baked_plugin_dest() -> Path:
    """Return the npm package copy of bake output.

    Returns:
        Absolute path under ``npm/ai-skills/data/plugins-baked/``.
    """
    return DATA_ROOT / PLUGINS_BAKED_DIRNAME


def _remove_path(path: Path) -> None:
    """Remove a file, symlink, or directory tree if it exists.

    Args:
        path: Path to unlink or recursively delete.
    """
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if path.is_dir():
        shutil.rmtree(path)


def _baked_plugin_files(*, root: Path) -> dict[str, bytes]:
    """Map POSIX-relative paths to file bytes under a bake tree.

    Symlinks are skipped; bake validation already rejects them in the
    source tree. The dest copy is written with ``symlinks=False``.

    Args:
        root: ``plugins-baked`` directory.

    Returns:
        Relative path → contents for every regular file.
    """
    files: dict[str, bytes] = {}
    if not root.is_dir() or root.is_symlink():
        return files
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def write_baked_plugins() -> None:
    """Copy local bake output into the npm package, or remove a stale copy.

    When ``plugins-baked/`` is absent, any previous package copy is
    deleted so a publish cannot ship leftover vendor trees.
    """
    source = baked_plugin_source()
    dest = baked_plugin_dest()
    _remove_path(dest)
    if not source.is_dir() or source.is_symlink():
        return
    shutil.copytree(src=source, dst=dest, symlinks=False)
    print(f"Wrote {dest.relative_to(PROJECT_ROOT)}")


def check_baked_plugins() -> bool:
    """Compare local bake output to the npm package copy when a bake exists.

    First-party sync checks are independent of this tree. When
    ``plugins-baked/`` is absent there is no committed vendor tree to
    drift-check, so this returns false (no drift).

    Returns:
        True when the package copy differs from a present bake tree.
    """
    source = baked_plugin_source()
    dest = baked_plugin_dest()
    if not source.is_dir() or source.is_symlink():
        return False
    expected = _baked_plugin_files(root=source)
    actual = _baked_plugin_files(root=dest)
    if expected == actual:
        return False
    only_expected = sorted(set(expected) - set(actual))
    only_actual = sorted(set(actual) - set(expected))
    changed = sorted(
        path
        for path in set(expected) & set(actual)
        if expected[path] != actual[path]
    )
    relative = dest.relative_to(PROJECT_ROOT)
    for path in only_expected:
        print(f"missing baked copy: {relative / path}", file=sys.stderr)
    for path in only_actual:
        print(f"extra baked copy: {relative / path}", file=sys.stderr)
    for path in changed:
        print(f"stale baked copy: {relative / path}", file=sys.stderr)
    return True


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
    write_baked_plugins()


def check_rendered(files: dict[Path, str]) -> int:
    """Report generated package files that differ from source data.

    Vendor bake output is compared only when a local ``plugins-baked/``
    tree exists. First-party catalog files are always checked.

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
    return int(has_drift or check_baked_plugins())


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
