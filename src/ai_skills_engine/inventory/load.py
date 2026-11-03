"""Load a deterministic inventory from explicit local or pinned vendor inputs."""

from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_skills_engine.bake.vendor_plugins import _materialize_vendor_tree
from ai_skills_engine.inventory.capability_id import CapabilityId
from ai_skills_engine.inventory.collect import collect_package
from ai_skills_engine.inventory.edges import resolve_edges
from ai_skills_engine.inventory.lint import lint_inventory
from ai_skills_engine.inventory.mapping import mapped_packages
from ai_skills_engine.inventory.model import Inventory
from ai_skills_engine.inventory.package_id import PackageId
from ai_skills_engine.inventory.payload import source_path
from ai_skills_engine.inventory.pending import PendingCapability
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.load import load_consumer, read_document
from ai_skills_engine.manifest.package import Package
from ai_skills_engine.manifest.validate import validate_document
from ai_skills_engine.manifest.vendor import Vendor
from ai_skills_engine.provenance.authorship import Authorship
from ai_skills_engine.provenance.context import Context, origin_locator
from ai_skills_engine.registry.vendor import Vendor as RegistryVendor


def load_inventory(
    root: Path,
    *,
    vendor_roots: Mapping[str, Path] | None = None,
    fetch_vendors: bool = False,
    selection_candidates: bool = False,
    identity_migrations: Mapping[str, str] | None = None,
) -> Inventory:
    """Collect immutable records and diagnostics without executing vendor bytes.

    Offline roots are caller-supplied snapshots; their pin is not certified by
    collection. Explicit fetching uses the existing SHA-pinned bake fetcher and
    a private temporary tree. Missing offline inputs remain visible warnings.

    Args:
        root: Consumer repository root.
        vendor_roots: Explicit local snapshots keyed by consumer vendor alias.
        fetch_vendors: Acquire missing trees using the existing pinned fetcher.
        selection_candidates: Retain all declared candidates before selection.
        identity_migrations: Validated publisher-local migration metadata.

    Returns:
        Sorted records and diagnostics, retaining errors for review.

    Raises:
        ValueError: On malformed declarations, unknown vendor-root aliases or
            unsafe fetched trees (including unrelated documentation symlinks).
        RuntimeError: On a failed explicitly requested pinned fetch.
    """
    return _load_inventory(
        root=root,
        vendor_roots=vendor_roots or {},
        fetch_vendors=fetch_vendors,
        selection_candidates=selection_candidates,
        identity_migrations=identity_migrations or {},
        context=None,
    )


def _load_inventory(
    *,
    root: Path,
    vendor_roots: Mapping[str, Path],
    fetch_vendors: bool,
    selection_candidates: bool,
    identity_migrations: Mapping[str, str],
    context: Context | None,
) -> Inventory:
    """Load one explicit publication within the recursive provenance boundary.

    Args:
        root: Publisher snapshot.
        vendor_roots: Slash-qualified pinned offline inputs.
        fetch_vendors: Explicit acquisition authorization.
        selection_candidates: Whether selection owns direct filtering.
        identity_migrations: Validated publisher identity migrations.
        context: Publication identity and final consumer policy.

    Returns:
        Complete observed inventory and provenance evidence.

    Raises:
        ValueError: For unsafe declarations or unknown offline aliases.
    """
    from ai_skills_engine.provenance.build import build_inventory
    from ai_skills_engine.provenance.publisher import metadata

    root = root.resolve()
    source_path(root=root, relative="ai-skills.yaml")
    document = read_document(root / "ai-skills.yaml")
    if context is not None:
        owned_migrations, _ = metadata(
            document=document, publisher=document["publisher"]["id"]
        )
        identity_migrations = {
            **owned_migrations,
            **identity_migrations,
            **dict(context.migrations),
        }
        document = {
            key: value
            for key, value in document.items()
            if key not in {"policy", "overrides"} and not key.startswith("x-")
        }
    structural = [item for item in validate_document(document) if item.code == "schema"]
    if structural:
        raise ValueError(str(structural))
    roots = {key: value.absolute() for key, value in (vendor_roots or {}).items()}
    aliases = {item["id"] for item in document.get("vendors", [])}
    unknown = {
        key
        for key in roots
        if key.split("/", 1)[0] not in aliases
        or ("/" in key and key.split("/", 1)[0] not in roots)
    }
    if unknown:
        raise ValueError(f"Unknown vendor-root aliases: {sorted(unknown)}")
    with TemporaryDirectory(prefix="ai-skills-inventory-") as temporary:
        if fetch_vendors:
            for item in document.get("vendors", []):
                if item["id"] not in roots:
                    vendor = RegistryVendor(
                        id=item["id"],
                        repo=item["repo"],
                        sha=item["sha"],
                        skill_roots=tuple(
                            item.get("mapping", {}).get("skillRoots", ())
                        ),
                        license=item.get("license", ""),
                        homepage=item.get("homepage", ""),
                    )
                    roots[vendor.id] = _materialize_vendor_tree(
                        vendor=vendor,
                        trees={},
                        temporary_root=Path(temporary),
                        prune_content_free_symlinks=False,
                    )
        inventory = _collect(
            root=root,
            roots=roots,
            supplied=set(vendor_roots or {}),
            selection_candidates=selection_candidates,
            identity_migrations=identity_migrations or {},
            ignore_authority=context is not None,
        )
        manifest, _, _ = load_consumer(
            root / "ai-skills.yaml",
            vendor_roots=roots,
            ignore_authority=context is not None,
        )
        publication = context or Context(
            origin=origin_locator(manifest.publisher.repo or manifest.publisher.id),
            rev=None,
            policy=manifest.policy,
            attestations=(
                tuple(
                    Authorship(
                        capability=item.capability, path=item.path, reason=item.reason
                    )
                    for item in manifest.overrides.attestations
                )
                if manifest.overrides
                else ()
            ),
            migrations=tuple(
                sorted(
                    {
                        **identity_migrations,
                        **(
                            {
                                item.from_: item.to
                                for item in manifest.overrides.migrations
                            }
                            if manifest.overrides
                            else {}
                        ),
                    }.items()
                )
            ),
        )
        return build_inventory(
            inventory=inventory,
            root=root,
            roots=roots,
            manifest=manifest,
            context=publication,
            fetch_vendors=fetch_vendors,
            selection_candidates=selection_candidates,
        )


def _collect(
    *,
    root: Path,
    roots: dict[str, Path],
    supplied: set[str],
    selection_candidates: bool,
    identity_migrations: Mapping[str, str],
    ignore_authority: bool,
) -> Inventory:
    """Collect local declarations and imports inside the input lifetime.

    Args:
        root: Consumer repository.
        roots: Available vendor snapshots.
        supplied: Unverified caller-provided snapshot aliases.
        selection_candidates: Defer all import filters to the selection layer.
        identity_migrations: Publisher-local identity moves for direct edges.
        ignore_authority: Strip publisher authority for recursive vendor inputs.

    Returns:
        Complete inventory observations.
    """
    for snapshot_root in roots.values():
        source_path(root=snapshot_root, relative=".")
        if (snapshot_root / "ai-skills.yaml").exists():
            source_path(root=snapshot_root, relative="ai-skills.yaml")
    consumer, imports, findings = load_consumer(
        root / "ai-skills.yaml", vendor_roots=roots, ignore_authority=ignore_authority
    )
    diagnostics = list(findings)
    pending: list[PendingCapability] = []
    resources: list[Resource] = []
    resource_paths: dict[ResourceId, Path] = {}
    rejected: list[CapabilityId | ResourceId] = []
    publishers = {
        consumer.publisher.id,
        *(vendor.id for vendor in consumer.vendors),
        *(manifest.publisher.id for manifest in imports.values()),
    }
    packages: list[tuple[Path, str, str, Package, dict[str, str], Vendor | None]] = [
        (
            root,
            consumer.publisher.id,
            consumer.publisher.repo or consumer.publisher.id,
            package,
            {},
            None,
        )
        for package in consumer.packages
    ]
    for vendor in consumer.vendors:
        vendor_root = roots.get(vendor.id)
        if vendor_root is None:
            diagnostics.append(
                Diagnostic(
                    "inventory.vendor-unavailable",
                    f"/vendors/{vendor.id}",
                    f"{vendor.repo}@{vendor.sha}: offline input unavailable; "
                    "use --vendor-root or --fetch-vendors; "
                    "host semantics remain unverified",
                    warning=True,
                )
            )
            continue
        if vendor.id in supplied:
            diagnostics.append(
                Diagnostic(
                    "inventory.vendor-pin-unverified",
                    f"/vendors/{vendor.id}",
                    f"Caller-supplied snapshot for {vendor.repo}@{vendor.sha}; "
                    "revision not verified by inventory",
                    warning=True,
                )
            )
        imported = imports.get(vendor.id)
        try:
            declarations = (
                tuple((package, {}) for package in imported.packages)
                if imported
                else mapped_packages(vendor=vendor, root=vendor_root)
            )
            for package, aliases in declarations:
                packages.append(
                    (
                        vendor_root.resolve(),
                        imported.publisher.id if imported else vendor.id,
                        vendor.repo,
                        package,
                        aliases,
                        vendor,
                    )
                )
        except (OSError, TypeError, ValueError) as error:
            diagnostics.append(
                Diagnostic(
                    "inventory.invalid-payload",
                    f"/vendors/{vendor.id}",
                    str(error).replace(str(vendor_root), "."),
                )
            )
    for source_root, publisher, origin, package, aliases, import_vendor in packages:
        package_id = PackageId(publisher=publisher, name=package.id)
        collect_package(
            root=source_root,
            package=package,
            package_id=package_id,
            origin=origin_locator(origin),
            aliases=aliases,
            vendor=None if selection_candidates else import_vendor,
            pending=pending,
            resources=resources,
            resource_paths=resource_paths,
            diagnostics=diagnostics,
            rejected=rejected,
        )
    capabilities, edge_findings, unresolved_edges = resolve_edges(
        pending=pending,
        resource_ids=tuple(item.id for item in resources),
        publishers=publishers,
        rejected=tuple(rejected),
        migrations={
            **identity_migrations,
            **(
                {item.from_: item.to for item in consumer.overrides.migrations}
                if consumer.overrides
                else {}
            ),
        },
    )
    diagnostics.extend(edge_findings)
    diagnostics.extend(
        lint_inventory(
            capabilities=capabilities,
            sources={item.capability.id: item.source for item in pending},
            resource_paths=resource_paths,
        )
    )
    return Inventory(
        capabilities=tuple(sorted(capabilities, key=lambda item: str(item.id))),
        resources=tuple(sorted(resources, key=lambda item: str(item.id))),
        rejected=tuple(sorted(set(rejected), key=str)),
        unresolved_edges=unresolved_edges,
        diagnostics=tuple(
            sorted(
                diagnostics,
                key=lambda item: (item.location, item.code, item.message, item.warning),
            )
        ),
    )
