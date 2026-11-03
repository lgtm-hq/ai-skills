"""Load a deterministic inventory from explicit local or pinned vendor inputs."""

from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_skills_engine.bake.vendor_plugins import _materialize_vendor_tree
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
from ai_skills_engine.registry.ingest_checks import (
    parse_allow,
    parse_limits,
    validate_input_tree,
)
from ai_skills_engine.registry.ingest_limits import IngestLimits
from ai_skills_engine.registry.vendor import Vendor as RegistryVendor


def load_inventory(
    root: Path,
    *,
    vendor_roots: Mapping[str, Path] | None = None,
    fetch_vendors: bool = False,
) -> Inventory:
    """Collect immutable records and diagnostics without executing vendor bytes.

    Offline roots are caller-supplied snapshots; their pin is not certified by
    collection. Explicit fetching uses the existing SHA-pinned bake fetcher and
    a private temporary tree. Missing offline inputs remain visible warnings.

    Args:
        root: Consumer repository root.
        vendor_roots: Explicit local snapshots keyed by consumer vendor alias.
        fetch_vendors: Acquire missing trees using the existing pinned fetcher.

    Returns:
        Sorted records and diagnostics, retaining errors for review.

    Raises:
        ValueError: On malformed declarations, unknown vendor-root aliases or
            unsafe fetched trees (including unrelated documentation symlinks).
        RuntimeError: On a failed explicitly requested pinned fetch.
    """
    root = root.resolve()
    source_path(root=root, relative="ai-skills.yaml")
    document = read_document(root / "ai-skills.yaml")
    structural = [item for item in validate_document(document) if item.code == "schema"]
    if structural:
        raise ValueError(str(structural))
    roots = {key: value.absolute() for key, value in (vendor_roots or {}).items()}
    aliases = {item["id"] for item in document.get("vendors", [])}
    if set(roots) - aliases:
        raise ValueError(f"Unknown vendor-root aliases: {sorted(set(roots) - aliases)}")
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
                        ingest_allow=parse_allow(
                            item.get("ingestAllow", []), label=item["id"]
                        ),
                        ingest_limits=(
                            parse_limits(item["ingestLimits"], label=item["id"])
                            if "ingestLimits" in item
                            else IngestLimits()
                        ),
                    )
                    roots[vendor.id] = _materialize_vendor_tree(
                        vendor=vendor,
                        trees={},
                        temporary_root=Path(temporary),
                        prune_content_free_symlinks=False,
                    )
        for item in document.get("vendors", []):
            if item["id"] in roots:
                validate_input_tree(
                    root=roots[item["id"]],
                    vendor=item["id"],
                    limits=(
                        parse_limits(item["ingestLimits"], label=item["id"])
                        if "ingestLimits" in item
                        else IngestLimits()
                    ),
                )
        return _collect(root=root, roots=roots, supplied=set(vendor_roots or {}))


def _collect(*, root: Path, roots: dict[str, Path], supplied: set[str]) -> Inventory:
    """Collect local declarations and imports inside the input lifetime.

    Args:
        root: Consumer repository.
        roots: Available vendor snapshots.
        supplied: Unverified caller-provided snapshot aliases.

    Returns:
        Complete inventory observations.
    """
    for snapshot_root in roots.values():
        source_path(root=snapshot_root, relative=".")
        if (snapshot_root / "ai-skills.yaml").exists():
            source_path(root=snapshot_root, relative="ai-skills.yaml")
    consumer, imports, findings = load_consumer(
        root / "ai-skills.yaml", vendor_roots=roots
    )
    diagnostics = list(findings)
    pending: list[PendingCapability] = []
    resources: list[Resource] = []
    resource_paths: dict[ResourceId, Path] = {}
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
            origin=(
                "github.com/" + origin
                if origin.count("/") == 1 and ":" not in origin
                else origin
            ),
            aliases=aliases,
            vendor=import_vendor,
            pending=pending,
            resources=resources,
            resource_paths=resource_paths,
            diagnostics=diagnostics,
        )
    capabilities, edge_findings = resolve_edges(
        pending=pending,
        resource_ids=tuple(item.id for item in resources),
        publishers=publishers,
        migrations=(
            {item.from_: item.to for item in consumer.overrides.migrations}
            if consumer.overrides
            else {}
        ),
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
        diagnostics=tuple(
            sorted(
                diagnostics,
                key=lambda item: (item.location, item.code, item.message, item.warning),
            )
        ),
    )
