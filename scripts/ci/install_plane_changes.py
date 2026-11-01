#!/usr/bin/env python3
"""Decide whether a PR changes any committed install-plane harness input."""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404 - read-only git diff with validated object IDs
from pathlib import Path

from install_plane_inputs import matches, patterns


def changed_files(base: str, head: str, repo: Path) -> list[str]:
    """List both sides of renames and deleted inputs in the PR's complete diff.

    Args:
        base: PR base commit ID.
        head: PR head commit ID.
        repo: Repository root with full comparison history.

    Returns:
        Changed repository-relative filenames.

    Raises:
        ValueError: If either object ID is invalid.
    """
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head)):
        raise ValueError("expected full PR base and head commit IDs")
    result = subprocess.run(  # nosec B603 B607 - fixed git command, SHA-only arguments
        args=["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...{head}"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return [os.fsdecode(name) for name in result.stdout.split(b"\0") if name]


def main() -> None:
    """Write the computed decision for the workflow's native matrix gate."""
    repo = Path(__file__).resolve().parents[2]
    event = json.loads(
        Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
    )
    pr = event.get("pull_request")
    changed = True
    if pr:
        files = changed_files(pr["base"]["sha"], pr["head"]["sha"], repo)
        globs = patterns(repo)
        inputs = [file for file in files if matches(file, globs)]
        print("Changed harness inputs:", json.dumps(inputs))
        changed = bool(inputs)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"changed={str(changed).lower()}\n")


if __name__ == "__main__":
    main()
