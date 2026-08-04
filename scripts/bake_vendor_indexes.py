#!/usr/bin/env python3
"""Bake SHA-pinned vendor skill indexes and the third-party NOTICE file.

Usage:
    uv run python scripts/bake_vendor_indexes.py
    uv run python scripts/bake_vendor_indexes.py --check
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from http.client import HTTPException, HTTPSConnection
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from vendor_registry.registry import (
    discover_skills,
    load_registry,
    render_index,
    render_notice,
    validate_index,
)
from vendor_registry.vendor import Vendor


def _repo_root() -> Path:
    """Return the repository root (parent of ``scripts/``).

    Returns:
        Absolute path to the repository root.
    """
    return Path(__file__).resolve().parents[1]


def _fetch_tree_paths(*, vendor: Vendor) -> list[str]:
    """Fetch blob paths from the vendor's pinned GitHub tree.

    Args:
        vendor: Vendor whose repository and SHA identify the source tree.

    Returns:
        Paths of every blob in the recursive pinned Git tree.

    Raises:
        RuntimeError: If GitHub cannot return a complete tree response.
        TypeError: If the GitHub tree payload is not a list of entries.
    """
    target = f"/repos/{vendor.repo}/git/trees/{vendor.sha}?recursive=1"
    # nosemgrep - fixed GitHub host; Python 3.13 HTTPSConnection verifies TLS.
    connection = HTTPSConnection(
        host="api.github.com",
        timeout=30,
    )
    try:
        connection.request(
            method="GET",
            url=target,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "lgtm-hq-ai-skills-vendor-index-baker",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            msg = (
                f"GitHub returned HTTP {response.status} for {vendor.repo}@{vendor.sha}"
            )
            raise RuntimeError(msg)
        data: Any = json.load(response)
    except (HTTPException, OSError) as error:
        msg = f"Could not fetch pinned tree for {vendor.repo}@{vendor.sha}: {error}"
        raise RuntimeError(msg) from error
    finally:
        connection.close()
    if not isinstance(data, dict) or data.get("truncated") is True:
        msg = f"GitHub returned an incomplete tree for {vendor.repo}@{vendor.sha}"
        raise RuntimeError(msg)
    tree = data.get("tree")
    if not isinstance(tree, list):
        msg = f"GitHub returned no tree entries for {vendor.repo}@{vendor.sha}"
        raise TypeError(msg)
    paths: list[str] = []
    for entry in tree:
        if isinstance(entry, dict) and entry.get("type") == "blob":
            path = entry.get("path")
            if isinstance(path, str):
                paths.append(path)
    return paths


def _check_rendered(*, actual_path: Path, expected: str) -> int:
    """Check a generated file against expected content and emit a diff.

    Args:
        actual_path: Generated file to compare.
        expected: Fresh generated content.

    Returns:
        ``0`` when the file matches, otherwise ``1``.
    """
    if not actual_path.is_file():
        print(f"Missing generated file: {actual_path}", file=sys.stderr)
        return 1
    actual = actual_path.read_text(encoding="utf-8")
    if actual == expected:
        return 0
    sys.stderr.writelines(
        difflib.unified_diff(
            actual.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=str(actual_path),
            tofile="generated",
        ),
    )
    print(f"Generated file is stale: {actual_path}", file=sys.stderr)
    return 1


def bake(*, repo_root: Path) -> None:
    """Fetch pins and write all committed vendor indexes and NOTICE.md.

    Args:
        repo_root: Repository root containing ``vendors.yaml``.
    """
    vendors = load_registry(registry_path=repo_root / "vendors.yaml")
    discovered_skills = [
        (
            vendor,
            discover_skills(
                paths=_fetch_tree_paths(vendor=vendor),
                skill_roots=vendor.skill_roots,
            ),
        )
        for vendor in vendors
    ]
    indexes_dir = repo_root / "vendor-indexes"
    with TemporaryDirectory(dir=repo_root) as temporary_directory:
        temporary_root = Path(temporary_directory)
        temporary_indexes_dir = temporary_root / "vendor-indexes"
        temporary_indexes_dir.mkdir()
        for vendor, skills in discovered_skills:
            (temporary_indexes_dir / f"{vendor.id}.json").write_text(
                render_index(vendor=vendor, skills=skills),
                encoding="utf-8",
            )
        temporary_notice_path = temporary_root / "NOTICE.md"
        temporary_notice_path.write_text(
            render_notice(vendors=vendors), encoding="utf-8"
        )

        indexes_dir.mkdir(parents=True, exist_ok=True)
        for vendor, skills in discovered_skills:
            index_path = indexes_dir / f"{vendor.id}.json"
            os.replace(temporary_indexes_dir / index_path.name, index_path)
            print(f"Wrote {index_path.relative_to(repo_root)} ({len(skills)} skills)")
        notice_path = repo_root / "NOTICE.md"
        os.replace(temporary_notice_path, notice_path)
        print(f"Wrote {notice_path.relative_to(repo_root)}")


def check(*, repo_root: Path) -> int:
    """Validate registry and baked artifacts without network access.

    Args:
        repo_root: Repository root containing generated vendor artifacts.

    Returns:
        ``0`` when every artifact is valid and current, otherwise ``1``.
    """
    try:
        vendors = load_registry(registry_path=repo_root / "vendors.yaml")
        for vendor in vendors:
            validate_index(
                index_path=repo_root / "vendor-indexes" / f"{vendor.id}.json",
                vendor=vendor,
            )
    except (OSError, TypeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return _check_rendered(
        actual_path=repo_root / "NOTICE.md",
        expected=render_notice(vendors=vendors),
    )


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and bake or check vendor registry artifacts.

    Args:
        argv: CLI arguments, defaulting to process arguments.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate committed indexes and NOTICE.md without GitHub access",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root override (default: parent of scripts/)",
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root if args.repo_root is not None else _repo_root()
    if args.check:
        return check(repo_root=repo_root)
    bake(repo_root=repo_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
