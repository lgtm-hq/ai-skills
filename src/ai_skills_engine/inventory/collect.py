"""Observe one package's explicitly declared payloads and import boundary."""

from pathlib import Path, PurePosixPath

from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.capability_id import CapabilityId
from ai_skills_engine.inventory.host_attributes import inspect_attributes
from ai_skills_engine.inventory.package_id import PackageId
from ai_skills_engine.inventory.payload import payload_files, source_path, tree_digest
from ai_skills_engine.inventory.pending import PendingCapability
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.inventory.roles import destination_names, inspect_role
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.identity import matches
from ai_skills_engine.manifest.package import Package
from ai_skills_engine.manifest.vendor import Vendor


def _included(*, identity: str, vendor: Vendor | None) -> bool:
    """Apply only the declared direct import boundary, without dependency closure.

    Args:
        identity: Observed identity.
        vendor: Import declaration, absent for local publications.

    Returns:
        Whether this record is directly imported.
    """
    return vendor is None or (
        (
            vendor.include is None
            or any(
                matches(selector=selector, identity=identity)
                for selector in vendor.include
            )
        )
        and not any(
            matches(selector=selector, identity=identity)
            for selector in vendor.exclude or ()
        )
    )


def collect_package(
    *,
    root: Path,
    package: Package,
    package_id: PackageId,
    origin: str,
    aliases: dict[str, str],
    vendor: Vendor | None,
    pending: list[PendingCapability],
    resources: list[Resource],
    resource_paths: dict[ResourceId, Path],
    diagnostics: list[Diagnostic],
    rejected: list[CapabilityId | ResourceId],
) -> None:
    """Hash explicit package contents and retain per-payload failures.

    Args:
        root: Safe source repository.
        package: Publication declarations.
        package_id: Qualified package.
        origin: Original repository resource_identity.
        aliases: Explicit destination-name aliases.
        vendor: Direct import boundary, absent for locals.
        pending: Capability accumulator.
        resources: Resource accumulator.
        resource_paths: Physical resource boundaries.
        diagnostics: Findings accumulator.
        rejected: Typed identities of declarations whose payload was rejected.
    """
    for resource_declaration in package.resources:
        resource_identity = None
        try:
            resource_identity = ResourceId(
                package=package_id, name=resource_declaration.id
            )
            if not _included(identity=str(resource_identity), vendor=vendor):
                continue
            if resource_identity in resource_paths or resource_identity in rejected:
                previous = next(
                    (
                        item.source_path
                        for item in resources
                        if item.id == resource_identity
                    ),
                    "rejected payload",
                )
                diagnostics.append(
                    Diagnostic(
                        "inventory.duplicate-id",
                        str(resource_identity),
                        "Resource identity is not unique across inputs: "
                        f"{previous} conflicts with {resource_declaration.path}; "
                        "declare distinct resource IDs in a vendor manifest",
                    )
                )
                continue
            source = source_path(root=root, relative=resource_declaration.path)
            payload = payload_files(source)
            resources.append(
                Resource(
                    id=resource_identity,
                    origin=origin,
                    source_path=PurePosixPath(resource_declaration.path),
                    payload=payload,
                    tree_digest=tree_digest(payload),
                )
            )
            resource_paths[resource_identity] = source
        except (OSError, TypeError, ValueError) as error:
            if resource_identity is not None:
                rejected.append(resource_identity)
            diagnostics.append(
                Diagnostic(
                    "inventory.invalid-resource",
                    str(resource_identity) if resource_identity else str(package_id),
                    str(error).replace(str(root), "."),
                )
            )
    for declaration in package.capabilities:
        location = f"{package_id}:{declaration.role}/{declaration.id}"
        identity = None
        try:
            identity = CapabilityId.parse(location)
            if not _included(identity=location, vendor=vendor):
                continue
            if identity in rejected or any(
                item.capability.id == identity for item in pending
            ):
                diagnostics.append(
                    Diagnostic(
                        "inventory.duplicate-id",
                        location,
                        "Capability identity is not unique across inputs",
                    )
                )
                continue
            source = source_path(root=root, relative=declaration.path)
            payload = payload_files(source)
            dialect, metadata = inspect_role(source=source, role=declaration.role)
            attributes, findings = inspect_attributes(
                metadata=metadata, location=location
            )
            diagnostics.extend(findings)
            upstream = source.name if source.is_dir() else source.stem
            capability = Capability(
                id=identity,
                role=declaration.role,
                dialect=dialect,
                package=package_id,
                origin=origin,
                source_path=PurePosixPath(declaration.path),
                payload=payload,
                tree_digest=tree_digest(payload),
                aliases=(aliases[upstream],) if upstream in aliases else (),
                host_attributes=attributes,
                destination_names=destination_names(
                    source=source, role=declaration.role, metadata=metadata
                ),
            )
            pending.append(
                PendingCapability(
                    capability=capability, source=source, declaration=declaration
                )
            )
        except (OSError, TypeError, ValueError) as error:
            if identity is not None:
                rejected.append(identity)
            diagnostics.append(
                Diagnostic(
                    "inventory.invalid-payload",
                    location,
                    str(error).replace(str(root), "."),
                )
            )
