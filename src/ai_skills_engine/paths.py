"""Discover author repositories independently of the installed engine location."""

from __future__ import annotations

import argparse
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Walk upward to a directory containing pyproject.toml and skills/.

    Args:
        start: Search directory, defaulting to the current working directory.

    Returns:
        Absolute repository root.

    Raises:
        ValueError: If no ancestor contains both repository markers.
    """
    directory = (start if start is not None else Path.cwd()).resolve()
    for candidate in (directory, *directory.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "skills").is_dir():
            return candidate
    msg = f"No ai-skills repository above {directory}; use --repo-root PATH"
    raise ValueError(msg)


def resolve_repo_root(
    *, override: Path | None, parser: argparse.ArgumentParser
) -> Path:
    """Use an explicit root or report a discovery failure as a CLI error.

    Explicit roots retain the legacy ability to operate on small fixture trees.

    Args:
        override: Repository selected by the caller, if any.
        parser: Command parser for actionable diagnostics without a traceback.

    Returns:
        Selected repository path.
    """
    if override is not None:
        return override
    try:
        return find_repo_root()
    except ValueError as error:
        parser.error(str(error))
