#!/usr/bin/env python3
"""Generate ``.claude-plugin/marketplace.json`` from ``bundles.yaml``.

Each bundle group is one installable plugin: kebab-case ``id`` as ``name``,
display name, description, repo version, ``source: "./"``, ``strict: false``,
and a ``skills`` array of ``./skills/<id>`` paths (upstream-native slicing).
Skills listed under ``ungrouped`` are omitted from the manifest and appear in
the installer's "Other" bucket.

Plugin ``version`` is stamped from a root ``VERSION`` file when present,
otherwise ``pyproject.toml`` ``project.version``. When both exist they
must match — the two files are not independent sources of truth.

Usage:
    uv run python scripts/generate_marketplace.py          # write manifest
    uv run python scripts/generate_marketplace.py --check  # fail if stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_KEBAB_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class BundleGroup:
    """One named installer group from ``bundles.yaml``."""

    name: str
    skills: tuple[str, ...]
    description: str = ""
    plugin_id: str = ""


@dataclass(frozen=True)
class BundlesDocument:
    """Validated bundle configuration covering every skill exactly once."""

    groups: dict[str, BundleGroup]
    ungrouped: tuple[str, ...]


@dataclass(frozen=True)
class MarketplacePlugin:
    """One plugin entry written to ``marketplace.json``."""

    name: str
    display_name: str
    description: str
    version: str
    source: str
    skills: tuple[str, ...]
    strict: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable mapping for this plugin.

        Returns:
            Plugin object suitable for ``json.dumps``.
        """
        return {
            "name": self.name,
            "displayName": self.display_name,
            "description": self.description,
            "version": self.version,
            "source": self.source,
            "strict": self.strict,
            "skills": list(self.skills),
        }


@dataclass(frozen=True)
class MarketplaceManifest:
    """Top-level marketplace manifest object."""

    plugins: tuple[MarketplacePlugin, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable mapping for the manifest.

        Returns:
            Manifest object suitable for ``json.dumps``.
        """
        return {"plugins": [plugin.to_dict() for plugin in self.plugins]}


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


def _require_kebab_case(*, label: str, value: str) -> None:
    """Reject identifiers that are not kebab-case.

    Args:
        label: Human-readable field name for the error.
        value: Identifier to validate.

    Raises:
        ValueError: If ``value`` is not kebab-case.
    """
    if not _KEBAB_ID_PATTERN.fullmatch(value):
        msg = f"{label} {value!r} must be kebab-case"
        raise ValueError(msg)


def _read_repo_version(*, repo_root: Path) -> str:
    """Return the repo version stamped onto marketplace plugins.

    Prefers a root ``VERSION`` file (first line, stripped). Falls back to
    ``pyproject.toml`` ``project.version``.

    Args:
        repo_root: Repository root path.

    Returns:
        Version string, for example ``0.19.0``.

    Raises:
        ValueError: If neither source yields a non-empty version.
    """
    version_path = repo_root / "VERSION"
    file_version: str | None = None
    if version_path.is_file():
        lines = version_path.read_text(encoding="utf-8").splitlines()
        file_version = lines[0].strip() if lines else ""
        if not file_version:
            msg = "VERSION file is empty"
            raise ValueError(msg)
    pyproject_path = repo_root / "pyproject.toml"
    pyproject_version: str | None = None
    if pyproject_path.is_file():
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        raw_version = data.get("project", {}).get("version")
        if isinstance(raw_version, str) and raw_version:
            pyproject_version = raw_version
    if file_version and pyproject_version and file_version != pyproject_version:
        msg = (
            f"VERSION {file_version!r} does not match pyproject.toml "
            f"project.version {pyproject_version!r}"
        )
        raise ValueError(msg)
    version = file_version or pyproject_version
    if version:
        return version
    msg = "No VERSION file or pyproject.toml project.version to stamp plugins"
    raise ValueError(msg)


def _parse_bundle_group(*, group_id: str, group: object) -> BundleGroup:
    """Parse one bundle group mapping from YAML.

    Args:
        group_id: Key under ``groups`` in ``bundles.yaml``.
        group: Raw YAML value for the group.

    Returns:
        Parsed bundle group.

    Raises:
        TypeError: If the group structure is invalid.
        ValueError: If required fields are missing or malformed.
    """
    _require_kebab_case(label="Group key", value=group_id)
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
    description = group.get("description", "")
    if not isinstance(description, str):
        msg = f"Group {group_id!r} 'description' must be a string"
        raise TypeError(msg)
    if "id" not in group:
        msg = f"Group {group_id!r} must have a string 'id'"
        raise TypeError(msg)
    raw_id = group["id"]
    if not isinstance(raw_id, str) or not raw_id:
        msg = f"Group {group_id!r} must have a string 'id'"
        raise TypeError(msg)
    _require_kebab_case(label=f"Group {group_id!r} id", value=raw_id)
    parsed_skills: list[str] = []
    for skill_name in skills:
        if not isinstance(skill_name, str):
            msg = f"Group {group_id!r} has a non-string skill entry"
            raise TypeError(msg)
        parsed_skills.append(skill_name)
    return BundleGroup(
        name=display_name,
        skills=tuple(parsed_skills),
        description=description,
        plugin_id=raw_id,
    )


def _load_bundles(*, repo_root: Path) -> BundlesDocument:
    """Load and parse ``bundles.yaml``.

    Args:
        repo_root: Repository root path.

    Returns:
        Parsed bundle document.

    Raises:
        TypeError: If the file structure is invalid.
    """
    bundles_path = repo_root / "bundles.yaml"
    data = yaml.safe_load(bundles_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = "bundles.yaml must be a mapping"
        raise TypeError(msg)
    raw_groups = data.get("groups")
    if not isinstance(raw_groups, dict):
        msg = "bundles.yaml must contain a 'groups' mapping"
        raise TypeError(msg)
    groups = {
        group_id: _parse_bundle_group(group_id=group_id, group=group)
        for group_id, group in raw_groups.items()
    }
    raw_ungrouped = data.get("ungrouped", [])
    if not isinstance(raw_ungrouped, list):
        msg = "bundles.yaml 'ungrouped' must be a list"
        raise TypeError(msg)
    ungrouped: list[str] = []
    for skill_name in raw_ungrouped:
        if not isinstance(skill_name, str):
            msg = "ungrouped entries must be strings"
            raise TypeError(msg)
        ungrouped.append(skill_name)
    return BundlesDocument(groups=groups, ungrouped=tuple(ungrouped))


def _validate_bundles(
    *,
    repo_root: Path,
    bundles: BundlesDocument,
) -> None:
    """Ensure ``bundles.yaml`` covers every skill exactly once.

    Args:
        repo_root: Repository root path.
        bundles: Parsed bundle document.

    Raises:
        ValueError: On missing, duplicate, or unknown skill references.
    """
    discovered = _discover_skill_names(repo_root=repo_root)
    assigned: dict[str, str] = {}
    plugin_ids: dict[str, str] = {}

    for group_id, group in bundles.groups.items():
        if group.plugin_id in plugin_ids:
            msg = (
                f"Plugin id {group.plugin_id!r} is used by both "
                f"{plugin_ids[group.plugin_id]!r} and {group_id!r}"
            )
            raise ValueError(msg)
        plugin_ids[group.plugin_id] = group_id
        for skill_name in group.skills:
            if skill_name in assigned:
                msg = (
                    f"Skill {skill_name!r} is listed in both "
                    f"{assigned[skill_name]!r} and {group_id!r}"
                )
                raise ValueError(msg)
            assigned[skill_name] = group_id

    for skill_name in bundles.ungrouped:
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


def _build_marketplace(
    *,
    bundles: BundlesDocument,
    version: str,
) -> MarketplaceManifest:
    """Build the marketplace manifest object.

    Args:
        bundles: Parsed bundle document.
        version: Repo version stamped onto every plugin entry.

    Returns:
        Marketplace manifest ready for JSON serialization.
    """
    plugins = tuple(
        MarketplacePlugin(
            name=group.plugin_id,
            display_name=group.name,
            description=group.description,
            version=version,
            source="./",
            skills=tuple(f"./skills/{name}" for name in group.skills),
            strict=False,
        )
        for group in bundles.groups.values()
    )
    return MarketplaceManifest(plugins=plugins)


def _render_marketplace(*, manifest: MarketplaceManifest) -> str:
    """Serialize manifest JSON with a stable trailing newline.

    Args:
        manifest: Marketplace manifest object.

    Returns:
        UTF-8 JSON text ending with a newline.
    """
    return json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n"


def load_validated_bundles(*, repo_root: Path) -> BundlesDocument:
    """Load ``bundles.yaml`` and validate full, duplicate-free skill coverage.

    Shared by the marketplace and README generators so both read the same
    validated view of ``bundles.yaml``.

    Args:
        repo_root: Repository root path.

    Returns:
        Parsed and validated bundle document.
    """
    bundles = _load_bundles(repo_root=repo_root)
    _validate_bundles(repo_root=repo_root, bundles=bundles)
    return bundles


def generate_marketplace(*, repo_root: Path) -> str:
    """Validate bundles and return rendered ``marketplace.json`` content.

    Args:
        repo_root: Repository root path.

    Returns:
        Rendered JSON for ``.claude-plugin/marketplace.json``.
    """
    bundles = load_validated_bundles(repo_root=repo_root)
    version = _read_repo_version(repo_root=repo_root)
    manifest = _build_marketplace(bundles=bundles, version=version)
    return _render_marketplace(manifest=manifest)


def marketplace_output_path(*, repo_root: Path) -> Path:
    """Return the Claude marketplace adapter path.

    Args:
        repo_root: Repository root path.

    Returns:
        Absolute path to ``.claude-plugin/marketplace.json``.
    """
    return repo_root / ".claude-plugin" / "marketplace.json"


def marketplace_drift_message(*, repo_root: Path) -> str | None:
    """Return a drift error if the generated marketplace is missing or stale.

    Args:
        repo_root: Repository root path.

    Returns:
        Error message, or ``None`` when the file matches the generator.
    """
    output_path = marketplace_output_path(repo_root=repo_root)
    rendered = generate_marketplace(repo_root=repo_root)
    relative = output_path.relative_to(repo_root)
    if not output_path.is_file():
        return f"Missing {relative}; run uv run python scripts/generate_marketplace.py"
    existing = output_path.read_text(encoding="utf-8")
    if existing != rendered:
        return (
            f"{relative} is out of date; "
            "run uv run python scripts/generate_marketplace.py"
        )
    return None


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

    if args.check:
        message = marketplace_drift_message(repo_root=repo_root)
        if message is not None:
            print(message, file=sys.stderr)
            sys.exit(1)
        return

    rendered = generate_marketplace(repo_root=repo_root)
    output_path = marketplace_output_path(repo_root=repo_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
