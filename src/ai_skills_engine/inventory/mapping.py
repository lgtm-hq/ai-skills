"""Translate explicit legacy import mappings into inventory declarations."""

from pathlib import Path, PurePosixPath

from ai_skills_engine.inventory.payload import source_path
from ai_skills_engine.manifest.capability import Capability
from ai_skills_engine.manifest.identity import Role
from ai_skills_engine.manifest.mapped_package import MappedPackage
from ai_skills_engine.manifest.package import Package
from ai_skills_engine.manifest.resource_record import Resource
from ai_skills_engine.manifest.vendor import Vendor
from ai_skills_engine.registry.plugin_bake import (
    discover_skill_relpaths,
    expand_skills_roots,
)
from ai_skills_engine.registry.registry import GLOB_METACHARS, discover_skills
from ai_skills_engine.registry.safe_tree import walk_files


def mapped_packages(
    *, vendor: Vendor, root: Path
) -> tuple[tuple[Package, dict[str, str]], ...]:
    """Discover mapped skill/agent payloads while retaining explicit names/edges.

    Args:
        vendor: Consumer-owned mapping and pin.
        root: Locally materialized vendor bytes.

    Returns:
        Publication declarations with destination aliases keyed by source name.

    Raises:
        ValueError: On unsafe paths, missing selectors or unused declarations.
    """
    mapping = vendor.mapping
    if mapping is None:
        raise ValueError("Manifestless vendor requires consumer mapping")
    if mapping.packages is None:
        skills = discover_skills(
            paths=[path.relative_to(root).as_posix() for path in walk_files(root=root)],
            skill_roots=mapping.skill_roots,
        )
        return (
            (
                Package(
                    id=vendor.id,
                    capabilities=tuple(
                        Capability(id=skill["name"], path=skill["path"])
                        for skill in skills
                    ),
                ),
                {},
            ),
        )
    return tuple(
        _mapped_package(package=package, root=root) for package in mapping.packages
    )


def _mapped_package(
    *, package: MappedPackage, root: Path
) -> tuple[Package, dict[str, str]]:
    """Resolve one declared legacy slice, without baking or rewriting bytes.

    Args:
        package: Consumer slice declaration.
        root: Vendor tree.

    Returns:
        Package declarations and aliases.

    Raises:
        ValueError: On unsafe/missing paths or unused per-name declarations.
    """
    # Check the non-glob prefix before glob expansion, then each matched root.
    ancestors: list[str] = []
    for component in PurePosixPath(package.skills_root).parts:
        if any(char in GLOB_METACHARS for char in component):
            break
        ancestors.append(component)
    source_path(root=root, relative=PurePosixPath(*ancestors).as_posix())
    roots = expand_skills_roots(vendor_root=root, pattern=package.skills_root)
    if not roots:
        raise ValueError(f"skillsRoot matched no directories: {package.skills_root}")
    paths: list[tuple[str, Role]] = []
    for skills_root in roots:
        source_path(root=root, relative=skills_root.relative_to(root).as_posix())
        selectors = (
            discover_skill_relpaths(skills_root=skills_root)
            if package.skills == "*"
            else package.skills
        )
        paths.extend(
            ((skills_root / selector).relative_to(root).as_posix(), Role.SKILL)
            for selector in selectors
        )
    paths.extend((path, Role.SKILL) for path in package.extra_skills or ())
    paths.extend(
        (f"agents/{name}.md", Role.SPECIALIST) for name in package.agents or ()
    )
    declarations: list[Capability] = []
    names: set[str] = set()
    for path, role in sorted(set(paths)):
        name = (
            PurePosixPath(path).stem
            if role == Role.SPECIALIST
            else PurePosixPath(path).name
        )
        names.add(name)
        declaration = package.capabilities.get(name)
        declarations.append(
            Capability(
                id=declaration.id if declaration and declaration.id else name,
                path=path,
                role=role,
                requires=declaration.requires if declaration else (),
                related=declaration.related if declaration else (),
                resources=declaration.resources if declaration else (),
            )
        )
    unused = (set(package.capabilities) | set(package.rename_skills or {})) - names
    if unused:
        raise ValueError(f"Unused mapped capability/renameSkills: {sorted(unused)}")
    # extraFiles is an explicit resource declaration, not a dependency heuristic.
    resources = tuple(
        Resource(id=PurePosixPath(path).stem.lower().replace("_", "-"), path=path)
        for path in package.extra_files or ()
    )
    return Package(
        id=package.id, capabilities=tuple(declarations), resources=resources
    ), dict(package.rename_skills or {})
