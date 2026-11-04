#!/usr/bin/env python3
"""Generate the committed host marketplaces from the artifact index.

Writes ``.claude-plugin/marketplace.json``, ``.cursor-plugin/marketplace.json``
and the Codex ``.agents/plugins/marketplace.json``. All three are generated
adapters produced by :mod:`ai_skills_engine.envelopes`: do not edit them by
hand. The input is the artifact index for the publisher's exported packages
(built offline, or ``--index``), never ``bundles.yaml``. Repo-root entries may
reference in-repo slices only while each slice is byte-identical to its
artifact capability tree.

``--output`` instead writes a filtered envelope tree, honoring ``--exclude``
and ``--host``. The default built layout has per-plugin envelopes under
``plugins/<name>/`` plus all three marketplaces for every exported package in
the index; ``--layout slice`` previews filtered repo-root marketplaces.

The ``bundles.yaml`` reader below remains for the README generator and the
legacy registry projection.

Usage:
    uv run ai-skills-engine generate            # write committed marketplaces
    uv run ai-skills-engine generate --check    # drift gate
    uv run ai-skills-engine generate --index dist/artifacts/index.json \
        --output dist/envelopes --exclude PUBLISHER/PACKAGE:skill/NAME
    uv run python scripts/generate_marketplace.py [--check]   # compatibility
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml

from ai_skills_engine.envelopes import (
    ALL_HOSTS,
    EnvelopeError,
    Host,
    Layout,
    Marketplace,
    generate,
    rules,
    without_slice_projection,
    write_files,
)
from ai_skills_engine.generate.envelope_catalog import (
    catalog_packages,
    load_index,
    publisher_index,
)
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.paths import resolve_repo_root
from ai_skills_engine.registry.ingest_checks import safe_diagnostic
from ai_skills_engine.registry.safe_tree import install_directory

_KEBAB_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
GENERATED_NOTICE = "do not edit — regenerate via scripts/generate_marketplace.py"
BUILT_NOTICE = "do not edit — regenerate via ai-skills-engine generate"
BUILT_PLUGIN_ROOT = "plugins/"
_MARKETPLACE_NAME = "ai-skills"
_CATALOG_OWNER = "lgtm-hq"
# Repo-root text is retained byte for byte; built trees describe their input.
_MARKETPLACE_DESCRIPTION = "Harness-agnostic agent skills generated from bundles.yaml."
_BUILT_DESCRIPTION = "Harness-agnostic agent skills generated from the artifact index."
_REGENERATE = "run uv run python scripts/generate_marketplace.py"


@dataclass(frozen=True)
class BundleGroup:
    """One named installer group from ``bundles.yaml``."""

    name: str
    skills: tuple[str, ...]
    plugin_id: str
    description: str = ""

    def __post_init__(self) -> None:
        """Reject empty or non-kebab plugin ids before marketplace serialization.

        Raises:
            ValueError: If ``plugin_id`` is empty or not kebab-case.
        """
        if not self.plugin_id:
            msg = "plugin_id must be a non-empty kebab-case identifier"
            raise ValueError(msg)
        _require_kebab_case(label="plugin_id", value=self.plugin_id)


@dataclass(frozen=True)
class BundlesDocument:
    """Validated bundle configuration covering every skill exactly once."""

    groups: dict[str, BundleGroup]
    ungrouped: tuple[str, ...]


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
        ValueError: On missing, duplicate, or unknown skill references, or
            when a group's plugin id does not match its YAML key.
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

    for group_id, group in bundles.groups.items():
        if group.plugin_id != group_id:
            msg = f"Group {group_id!r} id {group.plugin_id!r} must match the group key"
            raise ValueError(msg)
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


def _marketplace(*, repo_root: Path, layout: Layout) -> Marketplace:
    """Return the catalog marketplace identity.

    ``VERSION`` and ``pyproject.toml`` keep their consistency check. Without
    either, the manifest's ``x-version`` or ``0.0.0-local`` applies, exactly as
    for local artifact package versions. The owner is the manifest publisher;
    a repository without a manifest publishes nothing under the catalog owner.

    Args:
        repo_root: Repository root path.
        layout: In-repo slices or built plugin directories.

    Returns:
        Marketplace identity stamped with the catalog version.
    """
    manifest = repo_root / "ai-skills.yaml"
    document = read_document(manifest) if manifest.is_file() else {}
    if (repo_root / "VERSION").is_file() or (repo_root / "pyproject.toml").is_file():
        version = _read_repo_version(repo_root=repo_root)
    else:
        version = str(document.get("x-version", "0.0.0-local"))
    sliced = layout is Layout.SLICE
    return Marketplace(
        name=_MARKETPLACE_NAME,
        owner=str(document.get("publisher", {}).get("id", _CATALOG_OWNER)),
        description=_MARKETPLACE_DESCRIPTION if sliced else _BUILT_DESCRIPTION,
        version=version,
        notice=GENERATED_NOTICE if sliced else BUILT_NOTICE,
        layout=layout,
        plugin_root="" if sliced else BUILT_PLUGIN_ROOT,
    )


def repo_marketplaces(
    *, repo_root: Path, index: Mapping[str, Any] | None = None
) -> dict[str, bytes]:
    """Generate the committed, unfiltered repo-root marketplaces.

    Args:
        repo_root: Repository root path.
        index: Artifact index; built offline for the publisher when omitted.

    Returns:
        Repository-relative marketplace path to exact bytes.
    """
    packages = catalog_packages(root=repo_root, include_vendors=False, slices=True)
    if index is None:
        index = publisher_index(repo_root) if packages else _empty_index()
    return generate(
        index,
        None,
        ALL_HOSTS,
        marketplace=_marketplace(repo_root=repo_root, layout=Layout.SLICE),
        packages=packages,
    )


def _empty_index() -> dict[str, Any]:
    """Return a valid index for a publisher without exported packages.

    Nothing is built when no first-party package is published, so unrelated
    unpublished skills cannot block the marketplace gate.

    Returns:
        Artifact index with no packages.
    """
    return {
        "artifactFormat": 1,
        "engineVersion": "0.0.0-empty",
        "apiVersion": "ai-skills.dev/v1",
        "rootPackage": None,
        "packages": [],
        "legalFiles": [],
    }


def _relative(*, host: Host) -> str:
    """Return a host marketplace's repository-relative path from the rules.

    Args:
        host: Marketplace host.

    Returns:
        POSIX relative path.
    """
    return str(rules()["hosts"][host]["marketplace"]["path"])


def _marketplace_text(*, repo_root: Path, host: Host) -> str:
    """Return one generated repo-root marketplace as text.

    Args:
        repo_root: Repository root path.
        host: Marketplace host.

    Returns:
        Rendered JSON.
    """
    return repo_marketplaces(repo_root=repo_root)[_relative(host=host)].decode("utf-8")


def generate_marketplace(*, repo_root: Path) -> str:
    """Return rendered Claude marketplace JSON.

    Args:
        repo_root: Repository root path.

    Returns:
        Rendered JSON for ``.claude-plugin/marketplace.json``.
    """
    return _marketplace_text(repo_root=repo_root, host=Host.CLAUDE)


def generate_cursor_marketplace(*, repo_root: Path) -> str:
    """Return rendered Cursor marketplace JSON.

    Args:
        repo_root: Repository root path.

    Returns:
        Rendered JSON for ``.cursor-plugin/marketplace.json``.
    """
    return _marketplace_text(repo_root=repo_root, host=Host.CURSOR)


def generate_codex_marketplace(*, repo_root: Path) -> str:
    """Return rendered Codex marketplace JSON.

    Args:
        repo_root: Repository root path.

    Returns:
        Rendered JSON for ``.agents/plugins/marketplace.json``.
    """
    return _marketplace_text(repo_root=repo_root, host=Host.CODEX)


def marketplace_output_path(*, repo_root: Path) -> Path:
    """Return the Claude marketplace adapter path.

    Args:
        repo_root: Repository root path.

    Returns:
        Absolute path to ``.claude-plugin/marketplace.json``.
    """
    return repo_root / _relative(host=Host.CLAUDE)


def cursor_marketplace_output_path(*, repo_root: Path) -> Path:
    """Return the Cursor marketplace adapter path.

    Args:
        repo_root: Repository root path.

    Returns:
        Absolute path to ``.cursor-plugin/marketplace.json``.
    """
    return repo_root / _relative(host=Host.CURSOR)


def codex_marketplace_output_path(*, repo_root: Path) -> Path:
    """Return the Codex marketplace adapter path.

    Args:
        repo_root: Repository root path.

    Returns:
        Absolute path to ``.agents/plugins/marketplace.json``.
    """
    return repo_root / _relative(host=Host.CODEX)


def marketplace_drift_message(
    *, repo_root: Path, index: Mapping[str, Any] | None = None
) -> str | None:
    """Return a drift error if any generated marketplace adapter is stale.

    Args:
        repo_root: Repository root path.
        index: Artifact index; built offline for the publisher when omitted.

    Returns:
        Error message, or ``None`` when every adapter matches the generator.
    """
    for relative, data in repo_marketplaces(repo_root=repo_root, index=index).items():
        path = repo_root / relative
        if not path.is_file() or path.is_symlink():
            return f"Missing {relative}; {_REGENERATE}"
        if path.read_bytes() != data:
            return f"{relative} is out of date; {_REGENERATE}"
    return None


def _write_output(*, destination: Path, files: Mapping[str, bytes]) -> None:
    """Atomically replace an ``--output`` envelope tree.

    Args:
        destination: Output directory.
        files: Relative path to exact bytes.

    Raises:
        EnvelopeError: If the output directory itself is a symlink.
    """
    # Only the replaced directory is guarded; its existing ancestors belong to
    # the caller and may legitimately be symlinks (macOS /var, a linked TMPDIR).
    if destination.is_symlink():
        raise EnvelopeError(f"Symlink rejected in envelope output path: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".envelopes-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "output"
        staged.mkdir()
        write_files(destination=staged, files=files)
        install_directory(source=staged, destination=destination)


def _output(
    *, args: argparse.Namespace, repo_root: Path, index: Mapping[str, Any] | None
) -> None:
    """Write a filtered envelope tree into ``--output``.

    The built layout (default) covers every exported package in a supplied
    index, or the publisher's packages when the index is built offline. The
    slice layout previews filtered repo-root marketplaces for the publisher.

    Args:
        args: Parsed command arguments.
        repo_root: Repository root path.
        index: Supplied catalog index; the publisher index is built when None.

    Raises:
        EnvelopeError: If an excluded capability is not in the index.
    """
    layout = Layout(args.layout)
    hosts = frozenset(map(Host, args.host)) if args.host else ALL_HOSTS
    include_vendors = index is not None and layout is Layout.BUILT
    if index is None:
        index = publisher_index(repo_root)
    keep = None
    if args.exclude:
        capabilities = {
            capability["id"]
            for package in index["packages"]
            for capability in package["capabilities"]
        }
        if unknown := sorted(set(args.exclude) - capabilities):
            raise EnvelopeError(
                f"Excluded capability is not in the artifact: {unknown[0]}"
            )
        keep = frozenset(capabilities - set(args.exclude))
    packages = catalog_packages(
        root=repo_root,
        include_vendors=include_vendors,
        slices=layout is Layout.SLICE,
    )
    files = generate(
        index,
        keep,
        hosts,
        marketplace=_marketplace(repo_root=repo_root, layout=layout),
        packages=packages,
    )
    _write_output(destination=args.output, files=files)
    _note_omissions(repo_root=repo_root, layout=layout, hosts=hosts, index=index)


def _note_omissions(
    *,
    repo_root: Path,
    layout: Layout,
    hosts: frozenset[Host],
    index: Mapping[str, Any],
) -> None:
    """Tell the author which packages an ``--output`` tree leaves out.

    Args:
        repo_root: Repository root path.
        layout: Output layout.
        hosts: Requested hosts.
        index: Index the output was generated from.
    """
    if layout is Layout.SLICE:
        for host in without_slice_projection(hosts):
            print(
                f"generate: note: {host} has no repo-root slice projection (it "
                "copies the whole tree at source.path), so its slice marketplace "
                "lists no package; use --layout built for native delivery (#384)",
                file=sys.stderr,
            )
        return
    indexed = {package["id"] for package in index["packages"]}
    omitted = [
        package.package
        for package in catalog_packages(
            root=repo_root, include_vendors=True, slices=False
        )
        if package.package not in indexed
    ]
    if omitted:
        print(
            f"generate: note: built output omits {len(omitted)} exported vendor "
            f"package(s) ({', '.join(omitted)}); pass a complete "
            "`ai-skills-engine build` index with --index to include them",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    """Write or check generated host marketplaces and envelopes.

    Args:
        argv: CLI arguments, defaulting to process arguments.

    Returns:
        Zero on success; stale adapters or generation errors exit with one.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Generate Claude, Cursor and Codex marketplaces and plugin envelopes "
            "from the artifact index"
        ),
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if a committed marketplace adapter is missing or out of date",
    )
    modes.add_argument(
        "--output",
        type=Path,
        help="Write a filtered envelope tree instead of the committed marketplaces",
    )
    parser.add_argument(
        "--index",
        type=Path,
        help="Catalog index.json from ai-skills-engine build (includes vendors)",
    )
    parser.add_argument(
        "--layout",
        choices=[str(layout) for layout in Layout],
        default=str(Layout.BUILT),
        help="Output only: built plugin directories (default) or repo-root slices",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="CAPABILITY_ID",
        help="Output only: drop a capability from every envelope and marketplace",
    )
    parser.add_argument(
        "--host",
        action="append",
        choices=[str(host) for host in Host],
        help="Output only: restrict hosts (default: all)",
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.output is None and (
        args.exclude or args.host or args.layout != Layout.BUILT
    ):
        parser.error("--exclude, --host and --layout require --output")

    # A symlinked checkout path is resolved once; envelope writers then guard
    # only what they create below it.
    repo_root = resolve_repo_root(override=args.repo_root, parser=parser).resolve()
    try:
        index = None if args.index is None else load_index(args.index)
        if args.output is not None:
            _output(args=args, repo_root=repo_root, index=index)
            return 0
        if args.check:
            message = marketplace_drift_message(repo_root=repo_root, index=index)
            if message is not None:
                print(message, file=sys.stderr)
                return 1
            return 0
        files = repo_marketplaces(repo_root=repo_root, index=index)
        write_files(destination=repo_root, files=files)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as error:
        print("generate: " + safe_diagnostic(str(error)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
