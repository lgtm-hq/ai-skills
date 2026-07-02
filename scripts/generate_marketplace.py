#!/usr/bin/env python3
"""Generate ``.claude-plugin/marketplace.json`` from ``bundles.yaml``.

The Vercel ``skills`` CLI reads ``marketplace.json`` to group skills in the
interactive installer (checkbox picker). Each group becomes a named section;
skills listed under ``ungrouped`` are omitted from the manifest and appear in
the installer's "Other" bucket.

Usage:
    uv run python scripts/generate_marketplace.py          # write manifest
    uv run python scripts/generate_marketplace.py --check  # fail if stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


def _repo_root() -> Path:
    """Return the repository root (parent of ``scripts/``).

    Returns:
        Absolute path to the ai-skills repository root.
    """
    return Path(__file__).resolve().parents[1]


def _discover_skill_names(*, repo_root: Path) -> set[str]:
    """List skill directory names under ``skills/``.

    Args:
        repo_root: Repository root path.

    Returns:
        Set of skill ids (directory basenames with a ``SKILL.md`` file).
    """
    skills_root = repo_root / "skills"
    names: set[str] = set()
    for entry in skills_root.iterdir():
        if entry.is_dir() and (entry / "SKILL.md").is_file():
            names.add(entry.name)
    return names


def _load_bundles(*, repo_root: Path) -> dict[str, Any]:
    """Load and parse ``bundles.yaml``.

    Args:
        repo_root: Repository root path.

    Returns:
        Parsed YAML mapping with ``groups`` and ``ungrouped`` keys.

    Raises:
        ValueError: If the file structure is invalid.
    """
    bundles_path = repo_root / "bundles.yaml"
    data = yaml.safe_load(bundles_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = "bundles.yaml must be a mapping"
        raise TypeError(msg)
    if "groups" not in data or not isinstance(data["groups"], dict):
        msg = "bundles.yaml must contain a 'groups' mapping"
        raise TypeError(msg)
    ungrouped = data.get("ungrouped", [])
    if not isinstance(ungrouped, list):
        msg = "bundles.yaml 'ungrouped' must be a list"
        raise TypeError(msg)
    return data


def _validate_bundles(
    *,
    repo_root: Path,
    bundles: dict[str, Any],
) -> None:
    """Ensure ``bundles.yaml`` covers every skill exactly once.

    Args:
        repo_root: Repository root path.
        bundles: Parsed bundles YAML.

    Raises:
        ValueError: On missing, duplicate, or unknown skill references.
    """
    discovered = _discover_skill_names(repo_root=repo_root)
    assigned: dict[str, str] = {}

    for group_id, group in bundles["groups"].items():
        if not isinstance(group, dict):
            msg = f"Group {group_id!r} must be a mapping"
            raise TypeError(msg)
        display_name = group.get("name")
        skills = group.get("skills")
        if not display_name or not isinstance(display_name, str):
            msg = f"Group {group_id!r} must have a string 'name'"
            raise TypeError(msg)
        if not isinstance(skills, list):
            msg = f"Group {group_id!r} must have a 'skills' list"
            raise TypeError(msg)
        for skill_name in skills:
            if not isinstance(skill_name, str):
                msg = f"Group {group_id!r} has a non-string skill entry"
                raise TypeError(msg)
            if skill_name in assigned:
                msg = (
                    f"Skill {skill_name!r} is listed in both "
                    f"{assigned[skill_name]!r} and {group_id!r}"
                )
                raise ValueError(msg)
            assigned[skill_name] = group_id

    ungrouped = bundles.get("ungrouped", [])
    for skill_name in ungrouped:
        if not isinstance(skill_name, str):
            msg = "ungrouped entries must be strings"
            raise TypeError(msg)
        if skill_name in assigned:
            msg = f"Skill {skill_name!r} is both grouped and ungrouped"
            raise ValueError(msg)
        assigned[skill_name] = "ungrouped"

    missing = discovered - set(assigned)
    if missing:
        msg = f"bundles.yaml missing skills: {', '.join(sorted(missing))}"
        raise ValueError(msg)

    unknown = set(assigned) - discovered
    if unknown:
        msg = (
            f"bundles.yaml references missing skill dirs: {', '.join(sorted(unknown))}"
        )
        raise ValueError(msg)


def _build_marketplace(*, bundles: dict[str, Any]) -> dict[str, Any]:
    """Build the marketplace manifest JSON object.

    Args:
        bundles: Parsed bundles YAML.

    Returns:
        Mapping suitable for ``json.dumps`` to ``marketplace.json``.
    """
    plugins: list[dict[str, Any]] = []
    for group in bundles["groups"].values():
        skill_paths = [f"./skills/{name}" for name in group["skills"]]
        plugins.append(
            {
                "name": group["name"],
                "source": "./",
                "skills": skill_paths,
            },
        )
    return {"plugins": plugins}


def _render_marketplace(*, manifest: dict[str, Any]) -> str:
    """Serialize manifest JSON with a stable trailing newline.

    Args:
        manifest: Marketplace manifest object.

    Returns:
        UTF-8 JSON text ending with a newline.
    """
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def generate_marketplace(*, repo_root: Path) -> str:
    """Validate bundles and return rendered ``marketplace.json`` content.

    Args:
        repo_root: Repository root path.

    Returns:
        Rendered JSON for ``.claude-plugin/marketplace.json``.
    """
    bundles = _load_bundles(repo_root=repo_root)
    _validate_bundles(repo_root=repo_root, bundles=bundles)
    manifest = _build_marketplace(bundles=bundles)
    return _render_marketplace(manifest=manifest)


def main() -> None:
    """CLI entry: write or check ``.claude-plugin/marketplace.json``."""
    parser = argparse.ArgumentParser(
        description="Generate .claude-plugin/marketplace.json from bundles.yaml",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if marketplace.json is missing or out of date",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    rendered = generate_marketplace(repo_root=repo_root)
    output_path = repo_root / ".claude-plugin" / "marketplace.json"

    if args.check:
        if not output_path.is_file():
            print(
                f"Missing {output_path.relative_to(repo_root)}; "
                "run uv run python scripts/generate_marketplace.py",
                file=sys.stderr,
            )
            sys.exit(1)
        existing = output_path.read_text(encoding="utf-8")
        if existing != rendered:
            print(
                f"{output_path.relative_to(repo_root)} is out of date; "
                "run uv run python scripts/generate_marketplace.py",
                file=sys.stderr,
            )
            sys.exit(1)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
