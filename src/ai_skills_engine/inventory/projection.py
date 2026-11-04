"""Expand explicit artifact closures without inferring dependency edges."""

from dataclasses import replace

from ai_skills_engine.inventory.package_id import PackageId
from ai_skills_engine.manifest.package import Package


def project_package(*, package: Package, package_id: PackageId) -> Package:
    """Attach artifact resources to the ordinary authenticated inventory path.

    Args:
        package: Original publication declaration, including optional projection.
        package_id: Qualified publication identity used for resource edges.

    Returns:
        Effective artifact declaration with explicit resource edges.

    Raises:
        ValueError: For duplicate resources, unknown bindings or unused resources.
    """
    projection = package.artifact_resources
    if projection is None:
        return package
    resources = (*package.resources, *projection.resources)
    identities = [resource.id for resource in resources]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate ordinary/artifact resource identity")
    declared = {resource.id for resource in projection.resources}
    capabilities = {f"{cap.role}/{cap.id}" for cap in package.capabilities}
    if unknown := set(projection.bindings) - capabilities:
        raise ValueError(f"Unknown artifact resource capability: {sorted(unknown)}")
    bound = {name for names in projection.bindings.values() for name in names}
    if unknown := bound - declared:
        raise ValueError(f"Unknown artifact resource IDs: {sorted(unknown)}")
    if unused := declared - bound:
        raise ValueError(f"Unbound artifact resource IDs: {sorted(unused)}")
    return replace(
        package,
        resources=resources,
        capabilities=tuple(
            replace(
                cap,
                resources=tuple(
                    sorted(
                        {
                            *cap.resources,
                            *(
                                f"{package_id}:resource/{name}"
                                for name in projection.bindings.get(
                                    f"{cap.role}/{cap.id}", ()
                                )
                            ),
                        }
                    )
                ),
            )
            for cap in package.capabilities
        ),
    )
