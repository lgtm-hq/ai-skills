"""Slice one vendor tree into canonical plugin directories."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from skill_frontmatter import read_frontmatter_name, rewrite_frontmatter_name

from vendor_registry.plugin_bake_result import PluginBakeResult
from vendor_registry.plugin_manifest import write_plugin_manifests
from vendor_registry.plugin_version import plugin_version
from vendor_registry.safe_tree import (
    contained_path,
    copy_tree,
    iter_directory_entries,
    validate_tree,
    walk_files,
)
from vendor_registry.vendor import Vendor
from vendor_registry.vendor_plugin import VendorPlugin

_GLOB_METACHARS = frozenset("*?[]{}")
_AGENTS_DIRECTORY = "agents"


def bake_vendor_plugins(
    *,
    vendor: Vendor,
    vendor_root: Path,
    output_root: Path,
) -> tuple[PluginBakeResult, ...]:
    """Bake every plugin slice declared for ``vendor``.

    Args:
        vendor: Registry record.
        vendor_root: Unpacked pinned vendor tree.
        output_root: ``plugins-baked`` directory receiving plugin trees.

    Returns:
        One result per declared plugin, in registry order.

    Raises:
        ValueError: If a declared path is missing, a symlink is present, a
            path escapes the vendor tree, or a skill name collides inside
            one plugin.
    """
    contained_path(path=vendor_root, root=vendor_root)
    return tuple(
        _bake_plugin(
            vendor=vendor,
            plugin=plugin,
            vendor_root=vendor_root,
            output_root=output_root,
        )
        for plugin in vendor.plugins
    )


def discover_skill_relpaths(*, skills_root: Path) -> tuple[str, ...]:
    """Find skill directories under ``skills_root`` without entering them.

    A directory is a skill when it contains ``SKILL.md``. Nested
    ``SKILL.md`` files inside that directory are copied with the skill,
    not discovered as separate skills.

    Args:
        skills_root: Expanded skills-root directory.

    Returns:
        POSIX paths relative to ``skills_root``, sorted.
    """
    found: list[str] = []
    _discover(directory=skills_root, relative="", found=found)
    return tuple(sorted(found))


def _discover(*, directory: Path, relative: str, found: list[str]) -> None:
    """Walk containers until each ``SKILL.md`` directory is recorded.

    Args:
        directory: Current container.
        relative: POSIX path of ``directory`` relative to the skills root.
        found: Accumulator for discovered skill relpaths.
    """
    for child in iter_directory_entries(directory=directory):
        if child.is_symlink():
            msg = f"symlink rejected: {child}"
            raise ValueError(msg)
        if not child.is_dir():
            if not child.is_file():
                msg = f"unsupported file type rejected: {child}"
                raise ValueError(msg)
            continue
        child_relative = f"{relative}/{child.name}" if relative else child.name
        skill_markdown = child / "SKILL.md"
        if skill_markdown.is_symlink():
            msg = f"symlink rejected: {skill_markdown}"
            raise ValueError(msg)
        if skill_markdown.is_file():
            found.append(child_relative)
            continue
        _discover(directory=child, relative=child_relative, found=found)


def expand_skills_roots(*, vendor_root: Path, pattern: str) -> tuple[Path, ...]:
    """Resolve ``skillsRoot`` to concrete directories under ``vendor_root``.

    Args:
        vendor_root: Unpacked vendor tree.
        pattern: Literal relative path or glob.

    Returns:
        Matching directories in path order.

    Raises:
        ValueError: If a match is a symlink, or a literal root is missing.
    """
    if any(char in _GLOB_METACHARS for char in pattern):
        matches = []
        for path in sorted(vendor_root.glob(pattern)):
            if path.is_symlink():
                msg = f"symlink rejected: {path}"
                raise ValueError(msg)
            if path.is_dir():
                matches.append(path)
        return tuple(matches)
    path = vendor_root / pattern
    if path.is_symlink():
        msg = f"symlink rejected: {path}"
        raise ValueError(msg)
    if not path.is_dir():
        msg = f"skillsRoot missing: {pattern}"
        raise ValueError(msg)
    return (path,)


def _bake_plugin(
    *,
    vendor: Vendor,
    plugin: VendorPlugin,
    vendor_root: Path,
    output_root: Path,
) -> PluginBakeResult:
    """Bake one plugin slice into ``output_root / plugin.id``.

    Args:
        vendor: Parent vendor.
        plugin: Slice to bake.
        vendor_root: Unpacked vendor tree.
        output_root: Baked plugins directory.

    Returns:
        Record of ingested paths and explode names.

    Raises:
        ValueError: On missing content, dest collisions, or unsafe paths.
        FileExistsError: If the plugin output directory already exists.
    """
    destination = output_root / plugin.id
    if destination.exists():
        msg = f"plugin output already exists: {plugin.id}"
        raise FileExistsError(msg)
    destination.mkdir(parents=True)
    skills_destination = destination / "skills"
    skills_destination.mkdir()
    rename_map = dict(plugin.rename_skills)
    ingested: list[str] = []
    explode_names: list[str] = []
    renamed: list[tuple[str, str]] = []
    skills_roots = expand_skills_roots(
        vendor_root=vendor_root,
        pattern=plugin.skills_root,
    )
    if not skills_roots:
        msg = f"skillsRoot matched no directories: {plugin.skills_root}"
        raise ValueError(msg)

    for skills_root in skills_roots:
        selectors = (
            discover_skill_relpaths(skills_root=skills_root)
            if plugin.skills == "*"
            else plugin.skills
        )
        for selector in selectors:
            _ingest_skill(
                source=skills_root / selector,
                vendor_root=vendor_root,
                skills_destination=skills_destination,
                rename_map=rename_map,
                ingested=ingested,
                explode_names=explode_names,
                renamed=renamed,
            )

    for extra in plugin.extra_skills:
        _ingest_skill(
            source=vendor_root / extra,
            vendor_root=vendor_root,
            skills_destination=skills_destination,
            rename_map=rename_map,
            ingested=ingested,
            explode_names=explode_names,
            renamed=renamed,
        )

    applied = {old for old, _new in renamed}
    unused = [old for old, _new in plugin.rename_skills if old not in applied]
    if unused:
        msg = f"plugin {plugin.id} unused renameSkills {unused[0]!r}"
        raise ValueError(msg)

    agent_stems = _copy_agents(
        vendor=vendor,
        plugin=plugin,
        vendor_root=vendor_root,
        destination=destination,
    )
    if not ingested and not agent_stems:
        msg = f"plugin {plugin.id} ingested no skills or agents"
        raise ValueError(msg)
    version = plugin_version(sha=vendor.sha, display_ref=vendor.display_ref)
    write_plugin_manifests(
        destination=destination,
        plugin=plugin,
        vendor=vendor,
        version=version,
    )
    validate_tree(root=destination)
    return PluginBakeResult(
        plugin_id=plugin.id,
        version=version,
        ingested_skill_md=tuple(ingested),
        explode_names=tuple(explode_names),
        agent_stems=agent_stems,
        renamed=tuple(renamed),
    )


def _ingest_skill(
    *,
    source: Path,
    vendor_root: Path,
    skills_destination: Path,
    rename_map: dict[str, str],
    ingested: list[str],
    explode_names: list[str],
    renamed: list[tuple[str, str]],
) -> None:
    """Copy one skill directory and apply a registry rename if declared.

    Args:
        source: Skill directory in the vendor tree.
        vendor_root: Vendor tree root.
        skills_destination: Baked plugin ``skills/`` directory.
        rename_map: Old basename → new explode name.
        ingested: Accumulator of ingested ``SKILL.md`` relative paths.
        explode_names: Accumulator of post-rename skill directory names.
        renamed: Accumulator of applied ``(old, new)`` pairs.

    Raises:
        ValueError: If ``SKILL.md`` is missing or the dest name collides.
    """
    if source.is_symlink():
        msg = f"symlink rejected: {source}"
        raise ValueError(msg)
    skill_markdown = source / "SKILL.md"
    if skill_markdown.is_symlink():
        msg = f"symlink rejected: {skill_markdown}"
        raise ValueError(msg)
    if not source.is_dir() or not skill_markdown.is_file():
        msg = f"vendor skill missing SKILL.md: {source}"
        raise ValueError(msg)
    original_name = source.name
    out_name = rename_map.get(original_name, original_name)
    skill_destination = skills_destination / out_name
    if skill_destination.exists():
        msg = f"skill name collision in plugin: {out_name}"
        raise ValueError(msg)
    copy_tree(
        source=source,
        destination=skill_destination,
        source_root=vendor_root,
    )
    dest_markdown = skill_destination / "SKILL.md"
    if out_name != original_name:
        rewritten = rewrite_frontmatter_name(
            text=dest_markdown.read_text(encoding="utf-8"),
            name=out_name,
        )
        dest_markdown.write_text(rewritten, encoding="utf-8")
        renamed.append((original_name, out_name))
    baked_name = read_frontmatter_name(
        text=dest_markdown.read_text(encoding="utf-8"),
    )
    if baked_name != out_name:
        msg = (
            f"SKILL.md frontmatter name {baked_name!r} does not match "
            f"directory {out_name!r}"
        )
        raise ValueError(msg)
    ingested.extend(
        file_path.relative_to(vendor_root).as_posix()
        for file_path in walk_files(root=source)
        if file_path.name == "SKILL.md"
    )
    explode_names.append(out_name)


def _copy_agents(
    *,
    vendor: Vendor,
    plugin: VendorPlugin,
    vendor_root: Path,
    destination: Path,
) -> tuple[str, ...]:
    """Copy declared agent markdown files into the baked plugin.

    Agents are ingested from ``agents/<stem>.md`` at the vendor-tree root
    (the lab contract; there is no ``renameAgents`` field).

    Args:
        vendor: Parent vendor (for error context).
        plugin: Slice listing agent stems.
        vendor_root: Unpacked vendor tree.
        destination: Baked plugin directory.

    Returns:
        Ingested agent stems in registry order.

    Raises:
        ValueError: If a declared agent file is missing or a symlink.
    """
    if not plugin.agents:
        return ()
    agents_destination = destination / _AGENTS_DIRECTORY
    agents_destination.mkdir()
    for stem in plugin.agents:
        source = vendor_root / _AGENTS_DIRECTORY / f"{stem}.md"
        if source.is_symlink():
            msg = f"symlink rejected: {source}"
            raise ValueError(msg)
        if not source.is_file():
            msg = (
                f"vendor {vendor.id} plugin {plugin.id} agent missing: "
                f"{PurePosixPath(_AGENTS_DIRECTORY, f'{stem}.md')}"
            )
            raise ValueError(msg)
        contained_path(path=source, root=vendor_root)
        target = agents_destination / f"{stem}.md"
        target.write_bytes(source.read_bytes())
    return tuple(plugin.agents)
