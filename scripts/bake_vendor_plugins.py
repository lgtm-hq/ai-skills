#!/usr/bin/env python3
"""Bake registry plugin slices into a marketplace-shaped plugins-baked tree.

Usage:
    uv run python scripts/bake_vendor_plugins.py
    uv run python scripts/bake_vendor_plugins.py --check
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tarfile
from collections.abc import Mapping
from http.client import HTTPException, HTTPSConnection
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from skill_frontmatter import read_frontmatter_name
from vendor_registry.plugin_bake import bake_vendor_plugins
from vendor_registry.plugin_bake_result import PluginBakeResult
from vendor_registry.plugin_manifest import render_marketplace
from vendor_registry.plugin_report import (
    collect_agent_collisions,
    collect_skill_collisions,
    collision_error_message,
    render_coverage_report,
)
from vendor_registry.plugin_version import plugin_version
from vendor_registry.registry import load_registry
from vendor_registry.safe_tree import (
    find_skill_markdown,
    install_directory,
    validate_tree,
)
from vendor_registry.vendor import Vendor
from vendor_registry.vendor_plugin import VendorPlugin

PLUGINS_BAKED_DIRNAME = "plugins-baked"
COVERAGE_FILENAME = "COVERAGE.md"
MARKETPLACE_RELATIVE = Path(".claude-plugin") / "marketplace.json"
_USER_AGENT = "lgtm-hq-ai-skills-vendor-plugin-baker"
_MAX_REDIRECTS = 5


def _repo_root() -> Path:
    """Return the repository root (parent of ``scripts/``).

    Returns:
        Absolute path to the repository root.
    """
    return Path(__file__).resolve().parents[1]


def first_party_skill_names(*, repo_root: Path) -> frozenset[str]:
    """Return first-party skill directory names under ``skills/``.

    Args:
        repo_root: Repository root.

    Returns:
        Directory names that contain a ``SKILL.md``.
    """
    skills_root = repo_root / "skills"
    if not skills_root.is_dir() or skills_root.is_symlink():
        return frozenset()
    names: set[str] = set()
    for entry in skills_root.iterdir():
        if entry.is_symlink() or not entry.is_dir():
            continue
        if (entry / "SKILL.md").is_file() and not (entry / "SKILL.md").is_symlink():
            names.add(entry.name)
    return frozenset(names)


def bake(
    *,
    repo_root: Path,
    vendor_trees: Mapping[str, Path] | None = None,
) -> None:
    """Slice declared vendor plugins into ``plugins-baked/`` atomically.

    Vendor trees are fetched only for vendors that declare plugin slices.
    Index-only vendors are recorded in the coverage report without a fetch.

    Args:
        repo_root: Repository root containing ``vendors.yaml``.
        vendor_trees: Optional vendor-id → unpacked tree mapping for tests.

    Raises:
        RuntimeError: If a GitHub tarball cannot be fetched.
        ValueError: If bake validation or the collision report fails.
    """
    vendors = load_registry(registry_path=repo_root / "vendors.yaml")
    trees = dict(vendor_trees) if vendor_trees is not None else {}
    with TemporaryDirectory(dir=repo_root) as temporary_directory:
        temporary_root = Path(temporary_directory)
        output_root = temporary_root / PLUGINS_BAKED_DIRNAME
        output_root.mkdir()
        results, skipped_by_vendor, ingested_counts, fetched = _bake_into(
            vendors=vendors,
            trees=trees,
            temporary_root=temporary_root,
            output_root=output_root,
        )
        skill_collisions = collect_skill_collisions(
            results=results,
            first_party_names=first_party_skill_names(repo_root=repo_root),
        )
        agent_collisions = collect_agent_collisions(results=results)
        explode_name_count = len(
            {name for result in results for name in result.explode_names},
        )
        coverage = render_coverage_report(
            vendors=vendors,
            skipped_by_vendor=skipped_by_vendor,
            ingested_counts=ingested_counts,
            fetched_vendors=fetched,
            collisions=skill_collisions,
            agent_collisions=agent_collisions,
            explode_name_count=explode_name_count,
        )
        marketplace = render_marketplace(
            plugins=_marketplace_entries(vendors=vendors),
        )
        marketplace_path = output_root / MARKETPLACE_RELATIVE
        marketplace_path.parent.mkdir(parents=True, exist_ok=True)
        marketplace_path.write_text(marketplace, encoding="utf-8")
        (output_root / COVERAGE_FILENAME).write_text(coverage, encoding="utf-8")
        print(coverage, end="")
        if skill_collisions or agent_collisions:
            raise ValueError(
                collision_error_message(
                    skill_collisions=skill_collisions,
                    agent_collisions=agent_collisions,
                ),
            )
        validate_tree(root=output_root)
        install_directory(
            source=output_root,
            destination=repo_root / PLUGINS_BAKED_DIRNAME,
        )


def check(*, repo_root: Path) -> int:
    """Validate committed ``plugins-baked/`` without network access.

    Args:
        repo_root: Repository root containing generated bake output.

    Returns:
        ``0`` when the tree is valid and current, otherwise ``1``.
    """
    try:
        _check_baked_output(repo_root=repo_root)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


def _bake_into(
    *,
    vendors: tuple[Vendor, ...],
    trees: dict[str, Path],
    temporary_root: Path,
    output_root: Path,
) -> tuple[
    tuple[PluginBakeResult, ...],
    dict[str, tuple[str, ...]],
    dict[str, int],
    frozenset[str],
]:
    """Materialize vendor trees and bake declared plugin slices.

    Args:
        vendors: Registry vendors.
        trees: Optional pre-unpacked vendor trees keyed by vendor id.
        temporary_root: Scratch directory for fetched archives.
        output_root: Destination for baked plugin trees.

    Returns:
        Bake results, skipped SKILL.md paths, ingested counts, and the set
        of vendor ids whose trees were materialized.
    """
    results: list[PluginBakeResult] = []
    skipped_by_vendor: dict[str, tuple[str, ...]] = {}
    ingested_counts: dict[str, int] = {}
    fetched: set[str] = set()
    for vendor in vendors:
        if not vendor.plugins:
            continue
        vendor_root = _materialize_vendor_tree(
            vendor=vendor,
            trees=trees,
            temporary_root=temporary_root,
        )
        fetched.add(vendor.id)
        plugin_results = bake_vendor_plugins(
            vendor=vendor,
            vendor_root=vendor_root,
            output_root=output_root,
        )
        results.extend(plugin_results)
        ingested: set[str] = set()
        for result in plugin_results:
            ingested.update(result.ingested_skill_md)
        skipped_by_vendor[vendor.id] = tuple(
            path
            for path in find_skill_markdown(root=vendor_root)
            if path not in ingested
        )
        ingested_counts[vendor.id] = len(ingested)
        for result in plugin_results:
            for old, new in result.renamed:
                print(
                    f"bake: {vendor.id}:{old} RENAMED -> {result.plugin_id}/skills/{new}",
                )
    return tuple(results), skipped_by_vendor, ingested_counts, frozenset(fetched)


def _materialize_vendor_tree(
    *,
    vendor: Vendor,
    trees: dict[str, Path],
    temporary_root: Path,
) -> Path:
    """Return an unpacked vendor tree, fetching the pin when needed.

    Args:
        vendor: Registry record.
        trees: Optional local trees keyed by vendor id.
        temporary_root: Scratch directory for tarball extraction.

    Returns:
        Path to the unpacked vendor tree.

    Raises:
        ValueError: If a provided local tree is unsafe.
        RuntimeError: If GitHub cannot return the pinned tarball.
    """
    provided = trees.get(vendor.id)
    if provided is not None:
        validate_tree(root=provided)
        return provided
    dest = temporary_root / f"vendor-{vendor.id}"
    _fetch_vendor_tree(vendor=vendor, dest=dest)
    validate_tree(root=dest)
    return dest


def _fetch_vendor_tree(*, vendor: Vendor, dest: Path) -> None:
    """Download the pinned GitHub tarball into ``dest``.

    Args:
        vendor: Vendor whose ``repo`` and ``sha`` identify the archive.
        dest: Empty directory that will receive the unpacked tree.

    Raises:
        RuntimeError: If GitHub cannot return a complete tarball.
        ValueError: If the archive contains a path escape.
    """
    payload = _http_get_bytes(
        host="api.github.com",
        path=f"/repos/{vendor.repo}/tarball/{vendor.sha}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
        },
    )
    _extract_tarball(payload=payload, dest=dest)


def _http_get_bytes(
    *,
    host: str,
    path: str,
    headers: dict[str, str],
    redirects: int = _MAX_REDIRECTS,
) -> bytes:
    """GET ``path`` on ``host`` and follow a bounded number of redirects.

    Args:
        host: TLS host name.
        path: Request path including query string.
        headers: HTTP headers.
        redirects: Remaining redirects allowed.

    Returns:
        Response body.

    Raises:
        RuntimeError: On HTTP errors, truncated redirects, or transport
            failures.
    """
    # nosemgrep - fixed GitHub/codeload hosts; Python 3.13 HTTPSConnection verifies TLS.
    connection = HTTPSConnection(host=host, timeout=60)
    try:
        connection.request(method="GET", url=path, headers=headers)
        response = connection.getresponse()
        status = response.status
        location = response.getheader("Location")
        body = response.read()
    except (HTTPException, OSError) as error:
        msg = f"Could not fetch {host}{path}: {error}"
        raise RuntimeError(msg) from error
    finally:
        connection.close()
    if status in {301, 302, 303, 307, 308}:
        if not location or redirects <= 0:
            msg = f"GitHub tarball redirect failed for {host}{path}"
            raise RuntimeError(msg)
        parsed = urlparse(location)
        next_host = parsed.netloc or host
        next_path = parsed.path or "/"
        if parsed.query:
            next_path = f"{next_path}?{parsed.query}"
        return _http_get_bytes(
            host=next_host,
            path=next_path,
            headers=headers,
            redirects=redirects - 1,
        )
    if status != 200:
        msg = f"GitHub returned HTTP {status} for {host}{path}"
        raise RuntimeError(msg)
    return body


def _extract_tarball(*, payload: bytes, dest: Path) -> None:
    """Extract a GitHub tarball, stripping the top-level directory.

    Args:
        payload: Gzip-compressed tar bytes.
        dest: Directory that receives the stripped tree.

    Raises:
        ValueError: If a member would escape ``dest``.
        RuntimeError: If the archive cannot be read.
    """
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            members: list[tarfile.TarInfo] = []
            for member in archive.getmembers():
                rewritten = _rewrite_tarball_member(member=member)
                if rewritten is not None:
                    members.append(rewritten)
            archive.extractall(path=dest, members=members, filter="data")
    except (OSError, tarfile.TarError) as error:
        msg = f"Could not extract vendor tarball: {error}"
        raise RuntimeError(msg) from error


def _rewrite_tarball_member(*, member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Strip the GitHub root prefix and reject path escapes.

    Args:
        member: Archive member as stored by GitHub.

    Returns:
        The member with a dest-relative name, or ``None`` to skip the
        top-level directory itself.

    Raises:
        ValueError: If the member path is absolute or contains ``..``.
    """
    parts = PurePosixPath(member.name).parts
    if len(parts) < 2:
        return None
    relative = PurePosixPath(*parts[1:])
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        msg = f"path escape rejected: {member.name}"
        raise ValueError(msg)
    member.name = relative.as_posix()
    return member


def _marketplace_entries(
    *,
    vendors: tuple[Vendor, ...],
) -> list[dict[str, str]]:
    """Build marketplace plugin entries in registry order.

    Versions are pin-derived from the registry, never from on-disk manifests.

    Args:
        vendors: Registry vendors.

    Returns:
        Marketplace plugin objects.
    """
    entries: list[dict[str, str]] = []
    for vendor in vendors:
        for plugin in vendor.plugins:
            entries.append(
                {
                    "name": plugin.id,
                    "description": plugin.description,
                    "version": plugin_version(
                        sha=vendor.sha,
                        display_ref=vendor.display_ref,
                    ),
                    "source": f"./{plugin.id}",
                },
            )
    return entries


def _check_baked_output(*, repo_root: Path) -> None:
    """Fail closed if committed bake output is missing, stale, or unsafe.

    Args:
        repo_root: Repository root.

    Raises:
        ValueError: If the tree does not match the registry or is unsafe.
        json.JSONDecodeError: If a committed manifest is not JSON.
    """
    vendors = load_registry(registry_path=repo_root / "vendors.yaml")
    baked_root = repo_root / PLUGINS_BAKED_DIRNAME
    if not baked_root.is_dir() or baked_root.is_symlink():
        msg = f"Missing generated directory: {baked_root}"
        raise ValueError(msg)
    validate_tree(root=baked_root)
    coverage_path = baked_root / COVERAGE_FILENAME
    if not coverage_path.is_file():
        msg = f"Missing generated file: {coverage_path}"
        raise ValueError(msg)
    if not any(vendor.plugins for vendor in vendors):
        expected_coverage = render_coverage_report(
            vendors=vendors,
            skipped_by_vendor={},
            ingested_counts={},
            fetched_vendors=frozenset(),
            collisions=(),
            agent_collisions=(),
            explode_name_count=0,
        )
        if coverage_path.read_text(encoding="utf-8") != expected_coverage:
            msg = f"Generated file is stale: {coverage_path}"
            raise ValueError(msg)
    expected_ids = [plugin.id for vendor in vendors for plugin in vendor.plugins]
    actual_ids = sorted(
        path.name
        for path in baked_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )
    if sorted(expected_ids) != actual_ids:
        msg = (
            "plugins-baked plugin directories do not match vendors.yaml: "
            f"expected {expected_ids}, found {actual_ids}"
        )
        raise ValueError(msg)
    results = _results_from_disk(baked_root=baked_root, vendors=vendors)
    skill_collisions = collect_skill_collisions(
        results=results,
        first_party_names=first_party_skill_names(repo_root=repo_root),
    )
    agent_collisions = collect_agent_collisions(results=results)
    if skill_collisions or agent_collisions:
        raise ValueError(
            collision_error_message(
                skill_collisions=skill_collisions,
                agent_collisions=agent_collisions,
            ),
        )
    marketplace_path = baked_root / MARKETPLACE_RELATIVE
    expected_marketplace = render_marketplace(
        plugins=_marketplace_entries(vendors=vendors),
    )
    if not marketplace_path.is_file():
        msg = f"Missing generated file: {marketplace_path}"
        raise ValueError(msg)
    actual_marketplace = marketplace_path.read_text(encoding="utf-8")
    if actual_marketplace != expected_marketplace:
        msg = f"Generated file is stale: {marketplace_path}"
        raise ValueError(msg)


def _results_from_disk(
    *,
    baked_root: Path,
    vendors: tuple[Vendor, ...],
) -> tuple[PluginBakeResult, ...]:
    """Rebuild bake results from committed plugin trees for ``--check``.

    Registry fields (pin-derived version, ``renameSkills``, ``agents``,
    and explicit skill selectors) are the source of truth. Disk is only
    accepted when it matches those declarations.

    Args:
        baked_root: ``plugins-baked`` directory.
        vendors: Registry vendors (pin-derived versions and plugin ids).

    Returns:
        Synthetic results used for collision checks.

    Raises:
        ValueError: If a baked skill is missing ``SKILL.md``, frontmatter
            ``name`` does not match the directory, the stamped version
            is not pin-derived, or registry-declared skills/agents/renames
            are missing from the committed tree.
        json.JSONDecodeError: If ``plugin.json`` is invalid.
    """
    results: list[PluginBakeResult] = []
    for vendor in vendors:
        for plugin in vendor.plugins:
            plugin_dir = baked_root / plugin.id
            manifest = json.loads(
                (plugin_dir / "plugin.json").read_text(encoding="utf-8"),
            )
            expected_version = plugin_version(
                sha=vendor.sha,
                display_ref=vendor.display_ref,
            )
            version = str(manifest["version"])
            if version != expected_version:
                msg = (
                    f"baked plugin {plugin.id} version {version!r} does not "
                    f"match pin-derived {expected_version!r}"
                )
                raise ValueError(msg)
            explode_names = _baked_explode_names(plugin_dir=plugin_dir)
            disk_agents = _baked_agent_stems(plugin_dir=plugin_dir)
            _assert_plugin_matches_registry(
                plugin=plugin,
                explode_names=explode_names,
                disk_agents=disk_agents,
            )
            results.append(
                PluginBakeResult(
                    plugin_id=plugin.id,
                    version=version,
                    ingested_skill_md=(),
                    explode_names=explode_names,
                    agent_stems=plugin.agents,
                    renamed=plugin.rename_skills,
                ),
            )
    return tuple(results)


def _baked_explode_names(*, plugin_dir: Path) -> tuple[str, ...]:
    """Return frontmatter-validated skill directory names under a plugin.

    Args:
        plugin_dir: Baked plugin directory.

    Returns:
        Skill explode names in directory order.

    Raises:
        ValueError: If a skill directory is missing ``SKILL.md`` or its
            frontmatter ``name`` does not match the directory.
    """
    skills_root = plugin_dir / "skills"
    if not skills_root.is_dir() or skills_root.is_symlink():
        return ()
    names: list[str] = []
    for skill_dir in sorted(skills_root.iterdir(), key=lambda path: path.name):
        if skill_dir.is_symlink() or not skill_dir.is_dir():
            continue
        skill_markdown = skill_dir / "SKILL.md"
        if not skill_markdown.is_file() or skill_markdown.is_symlink():
            msg = f"baked skill missing SKILL.md: {skill_dir}"
            raise ValueError(msg)
        baked_name = read_frontmatter_name(
            text=skill_markdown.read_text(encoding="utf-8"),
        )
        if baked_name != skill_dir.name:
            msg = (
                f"SKILL.md frontmatter name {baked_name!r} does "
                f"not match directory {skill_dir.name!r}"
            )
            raise ValueError(msg)
        names.append(baked_name)
    return tuple(names)


def _baked_agent_stems(*, plugin_dir: Path) -> tuple[str, ...]:
    """Return ``agents/*.md`` stems from a baked plugin directory.

    Args:
        plugin_dir: Baked plugin directory.

    Returns:
        Agent stems in filename order.
    """
    agents_dir = plugin_dir / "agents"
    if not agents_dir.is_dir() or agents_dir.is_symlink():
        return ()
    return tuple(
        agent.stem
        for agent in sorted(agents_dir.iterdir(), key=lambda path: path.name)
        if agent.is_file() and not agent.is_symlink() and agent.suffix == ".md"
    )


def _assert_plugin_matches_registry(
    *,
    plugin: VendorPlugin,
    explode_names: tuple[str, ...],
    disk_agents: tuple[str, ...],
) -> None:
    """Fail closed when committed plugin contents lag ``vendors.yaml``.

    Args:
        plugin: Registry plugin declaration.
        explode_names: Skill directory names present on disk.
        disk_agents: Agent stems present on disk.

    Raises:
        ValueError: If rename targets, declared skills, extras, or agents
            do not match the committed tree.
    """
    disk_skills = frozenset(explode_names)
    rename_map = dict(plugin.rename_skills)
    for old, new in plugin.rename_skills:
        if old in disk_skills:
            msg = (
                f"baked plugin {plugin.id} still has pre-rename skill "
                f"{old!r}; expected {new!r}"
            )
            raise ValueError(msg)
        if new not in disk_skills:
            msg = f"baked plugin {plugin.id} missing renamed skill {new!r}"
            raise ValueError(msg)
    expected_names: list[str] = []
    if plugin.skills != "*":
        expected_names.extend(
            _renamed_basename(selector=selector, rename_map=rename_map)
            for selector in plugin.skills
        )
    expected_names.extend(
        _renamed_basename(selector=extra, rename_map=rename_map)
        for extra in plugin.extra_skills
    )
    missing = [name for name in expected_names if name not in disk_skills]
    if missing:
        msg = f"baked plugin {plugin.id} missing declared skill {missing[0]!r}"
        raise ValueError(msg)
    if frozenset(disk_agents) != frozenset(plugin.agents):
        msg = (
            f"baked plugin {plugin.id} agents {tuple(disk_agents)!r} do not "
            f"match registry {plugin.agents!r}"
        )
        raise ValueError(msg)


def _renamed_basename(*, selector: str, rename_map: dict[str, str]) -> str:
    """Return the post-rename skill directory name for a selector path.

    Args:
        selector: POSIX skill path relative to ``skillsRoot`` or repo root.
        rename_map: Old basename → new explode name.

    Returns:
        Directory name hosts will explode.
    """
    original = PurePosixPath(selector).name
    return rename_map.get(original, original)


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and bake or check vendor plugin trees.

    Args:
        argv: CLI arguments, defaulting to process arguments.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate committed plugins-baked/ without GitHub access",
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
