#!/usr/bin/env python3
"""Exchange generated vendor bytes as data, never as a checkout overlay."""

from __future__ import annotations

import base64
import binascii
import json
import os
import subprocess  # nosec B404 - fixed read-only git argv, no shell
import sys
import tempfile
from pathlib import Path
from typing import Any

GENERATED_FILES = frozenset({"NOTICE.md", "npm/ai-skills/NOTICE.md"})
GENERATED_DIRS = ("vendor-indexes/", "npm/ai-skills/data/")
# Conservative local budget, not a measured GitHub API limit.
MAX_BASE64_BYTES = 20 * 1024 * 1024
# Separate allowance for summary, paths, and JSON overhead.
MAX_ARTIFACT_BYTES = MAX_BASE64_BYTES + 1024 * 1024
MAX_COMMENT_CHARS = 65_536
SUMMARY_MARKER = "<!-- vendor-pin-regen -->"
ARTIFACT_NAME = "publication.json"


def validate_path(name: str) -> None:
    """Reject noncanonical paths and paths outside generated catalog data.

    Args:
        name: Repository-relative POSIX path, including deletion targets.

    Raises:
        ValueError: If a path is unsafe or outside the generated allowlist.
    """
    if (
        not name
        or "\\" in name
        or any(part in {"", ".", "..", ".git"} for part in name.split("/"))
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or name.startswith("npm/ai-skills/data/plugins-baked/")
        or (name not in GENERATED_FILES and not name.startswith(GENERATED_DIRS))
    ):
        msg = f"Refusing to commit a non-generated or noncanonical path: {name}"
        raise ValueError(msg)


def reject_symlinks(*, root: Path, path: Path) -> None:
    """Check a file and its ancestors only as far as the declared root.

    Args:
        root: Boundary directory; ancestors above it may be symlinks.
        path: File underneath the boundary.

    Raises:
        ValueError: If a symlink or lexical escape is encountered.
    """
    path.relative_to(root)
    for item in (path, *path.parents):
        if item.is_symlink():
            msg = f"Refusing to commit a symlink: {item}"
            raise ValueError(msg)
        if item == root:
            break


def validate_changes(changes: object) -> dict[str, list[dict[str, str]]]:
    """Validate untrusted GraphQL file records and enforce the payload budget.

    Args:
        changes: Decoded artifact file-change records.

    Returns:
        Validated additions and deletions.

    Raises:
        ValueError: If the schema, paths, base64, or combined size is invalid.
        TypeError: If a change collection is not a list.
    """
    if not isinstance(changes, dict) or set(changes) != {"additions", "deletions"}:
        raise ValueError("Invalid artifact fileChanges")
    seen: set[str] = set()
    size = 0
    for kind, fields in (
        ("additions", {"path", "contents"}),
        ("deletions", {"path"}),
    ):
        if not isinstance(changes[kind], list):
            raise TypeError("Invalid artifact change list")
        for item in changes[kind]:
            if (
                not isinstance(item, dict)
                or set(item) != fields
                or not all(isinstance(value, str) for value in item.values())
            ):
                raise ValueError("Invalid artifact change record")
            name = item["path"]
            validate_path(name)
            if name in seen:
                raise ValueError(f"Duplicate artifact path: {name}")
            seen.add(name)
            if kind == "additions":
                size += len(item["contents"])
                if size > MAX_BASE64_BYTES:
                    msg = f"Combined base64 payload exceeds {MAX_BASE64_BYTES} bytes"
                    raise ValueError(msg)
                try:
                    base64.b64decode(item["contents"], validate=True)
                except (ValueError, binascii.Error) as error:
                    raise ValueError(f"Invalid artifact base64: {name}") from error
    return changes


def read_artifact(*, directory: Path, expected_head: str) -> dict[str, Any]:
    """Read exactly one bounded data file without extracting onto trusted code.

    Args:
        directory: Dedicated downloaded artifact directory outside the checkout.
        expected_head: PR event SHA, never inferred from artifact metadata.

    Returns:
        Validated publication envelope.

    Raises:
        ValueError: If files, metadata, schema, or changes are unsafe.
    """
    path = directory / ARTIFACT_NAME
    reject_symlinks(root=directory, path=path)
    if set(directory.iterdir()) != {path} or not path.is_file():
        raise ValueError(
            "Artifact must contain only publication.json as a regular file"
        )
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError(f"Artifact exceeds {MAX_ARTIFACT_BYTES} bytes")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except RecursionError as error:
        raise ValueError("Artifact JSON nesting exceeds parser limit") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"head", "summary", "status", "fileChanges"}
        or payload["head"] != expected_head
        or not isinstance(payload["summary"], str)
        or not payload["summary"].strip()
        or type(payload["status"]) is not int
        or payload["status"] not in {0, 1}
    ):
        raise ValueError("Invalid artifact metadata or expected PR head")
    if len(SUMMARY_MARKER) + 1 + len(payload["summary"]) > MAX_COMMENT_CHARS:
        raise ValueError(f"Summary comment exceeds {MAX_COMMENT_CHARS} characters")
    changes = validate_changes(payload["fileChanges"])
    if payload["status"] and any(changes.values()):
        raise ValueError("A collision report must not contain file changes")
    return payload


def main() -> None:
    """Package only successful refresh output, or a collision report alone."""
    # Local import keeps the trusted reader independent of the collector.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ci.create_signed_commit import file_changes

    status = int(os.environ["SUMMARY_STATUS"])
    root = Path.cwd()
    head = subprocess.check_output(  # nosec B603 B607 - read-only git, no shell
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()
    payload = {
        "head": head,
        "summary": Path(os.environ["SUMMARY_PATH"]).read_text(encoding="utf-8"),
        "status": status,
        "fileChanges": (
            file_changes(repo_root=root)
            if status == 0
            else {"additions": [], "deletions": []}
        ),
    }
    directory = Path(os.environ["ARTIFACT_DIR"])
    path = directory / ARTIFACT_NAME
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        staging = Path(temporary)
        staged_path = staging / ARTIFACT_NAME
        staged_path.write_text(json.dumps(payload), encoding="utf-8")
        read_artifact(directory=staging, expected_head=head)
        staged_path.replace(path)


if __name__ == "__main__":
    main()
