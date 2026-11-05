"""Offline checks behind ``validate``: sources, own content, links and exports."""

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ai_skills_engine.commands.validate_report import Finding, Severity
from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.model import Inventory
from ai_skills_engine.inventory.payload import source_path
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.manifest.identity import matches
from ai_skills_engine.manifest.model import Manifest
from ai_skills_engine.registry.ingest_checks import (
    parse_allow,
    safe_diagnostic,
    scan_paths,
    validate_input_tree,
)
from ai_skills_engine.registry.ingest_limits import IngestLimits
from ai_skills_engine.registry.ingest_scan_budget import IngestScanBudget
from ai_skills_engine.registry.safe_tree import (
    assert_relative_markdown_target,
    iter_markdown_destinations,
    walk_files,
)
from ai_skills_engine.registry.vendor import Vendor as RegistryVendor
from ai_skills_engine.selection.model import SelectionResult
from ai_skills_engine.selection.state import State
from ai_skills_engine.source_cache import SourceCache, SourceCacheError, materialize

_DEPTH = 64
_SELECTED = frozenset({State.SELECTED, State.PULLED_IN})


def cached_sources(
    *, root: Path, cache: SourceCache, scratch: Path
) -> tuple[dict[str, Path], list[Finding]]:
    """Extract every declared pin, recursively, from the source cache only.

    Nothing is fetched: a missing source is a warning naming ``lock --fetch``.

    Args:
        root: Consumer repository.
        cache: Verified content-addressed source cache.
        scratch: Private directory receiving extracted trees.

    Returns:
        Slash-qualified alias to extracted tree, and availability warnings.
    """
    from ai_skills_engine.manifest.load import read_document

    roots: dict[str, Path] = {}
    findings: list[Finding] = []
    pending: list[tuple[Path, str, int]] = [(root, "", 0)]
    while pending:
        current, prefix, depth = pending.pop(0)
        if depth > _DEPTH:
            break
        for entry in read_document(current / "ai-skills.yaml").get("vendors", []):
            alias = prefix + str(entry.get("id"))
            vendor = RegistryVendor(
                id=alias,
                repo=str(entry.get("repo")),
                sha=str(entry.get("sha")),
                skill_roots=(),
                license="",
                homepage="",
            )
            destination = scratch / str(len(roots))
            try:
                materialize(cache=cache, vendor=vendor, dest=destination, fetcher=None)
            except (OSError, ValueError, SourceCacheError) as error:
                findings.append(
                    Finding(
                        "validate.vendor-source-unavailable",
                        f"/vendors/{alias}",
                        safe_diagnostic(str(error)).replace(str(cache.root), "cache"),
                        Severity.WARNING,
                    )
                )
                continue
            roots[alias] = destination
            if (destination / "ai-skills.yaml").is_file():
                pending.append((destination, alias + "/", depth + 1))
    return roots, findings


def _declared_paths(document: Mapping[str, Any]) -> Iterable[tuple[str, int, str]]:
    """Yield every local payload path the publisher declares.

    Args:
        document: Parsed manifest.

    Yields:
        JSON pointer, package index and repository-relative path.
    """
    for index, package in enumerate(document.get("packages", [])):
        for field in ("capabilities", "resources"):
            for offset, record in enumerate(package.get(field, [])):
                yield f"/packages/{index}/{field}/{offset}", index, record["path"]
        projected = package.get("artifactResources", {}).get("resources", [])
        for offset, record in enumerate(projected):
            yield (
                f"/packages/{index}/artifactResources/resources/{offset}",
                index,
                record["path"],
            )


def own_ingest(*, root: Path, document: Mapping[str, Any]) -> list[Finding]:
    """Apply the ADR 0006 ingest checks to the publisher's own declared content.

    Own-package acknowledgements come only from ``overrides.ingestAllow``.

    Args:
        root: Publisher repository.
        document: Parsed manifest.

    Returns:
        Errors for limit, mode, LFS or secret-shape failures.
    """
    publisher = str(document["publisher"]["id"])
    limits = IngestLimits()
    try:
        allow = parse_allow(
            document.get("overrides", {}).get("ingestAllow", []), label="overrides"
        )
    except ValueError as error:
        return [Finding("ingest.invalid-allow", "/overrides/ingestAllow", str(error))]
    budgets: dict[int, IngestScanBudget] = {}
    findings: list[Finding] = []
    for location, package, relative in _declared_paths(document):
        budget = budgets.setdefault(package, IngestScanBudget())
        try:
            source = source_path(root=root, relative=relative)
            if source.is_dir():
                validate_input_tree(root=source, vendor=publisher, limits=limits)
            files = walk_files(root=source) if source.is_dir() else (source,)
            scan_paths(
                paths=((path, path.relative_to(root).as_posix()) for path in files),
                vendor=publisher,
                limits=limits,
                allow=allow,
                budget=budget,
            )
        except (OSError, ValueError) as error:
            findings.append(
                Finding(
                    "ingest.rejected",
                    location,
                    safe_diagnostic(str(error)).replace(str(root), "."),
                )
            )
    return findings


def own_links(*, root: Path, inventory: Inventory, publisher: str) -> list[Finding]:
    """Require internal Markdown references to stay inside each capability.

    Capabilities with declared resources are checked after reference rewriting
    by the artifact build that ``lock --check`` reproduces.

    Args:
        root: Publisher repository.
        inventory: Loaded inventory.
        publisher: Own publisher namespace.

    Returns:
        Errors for escaping or missing local targets.
    """
    findings: list[Finding] = []
    for capability in inventory.capabilities:
        if capability.package.publisher != publisher or capability.resources:
            continue
        try:
            source = source_path(root=root, relative=str(capability.source_path))
            boundary = source if source.is_dir() else source.parent
            files = walk_files(root=source) if source.is_dir() else (source,)
            for path in files:
                if path.suffix.lower() not in {".md", ".markdown", ".mdc"}:
                    continue
                for target in iter_markdown_destinations(
                    text=path.read_text(encoding="utf-8")
                ):
                    assert_relative_markdown_target(
                        raw_target=target, file_path=path, root=boundary
                    )
        except (OSError, UnicodeDecodeError, ValueError) as error:
            findings.append(
                Finding(
                    "links.internal-reference",
                    str(capability.id),
                    safe_diagnostic(str(error)).replace(str(root), "."),
                )
            )
    return findings


def collisions(selection: SelectionResult) -> list[Finding]:
    """Report every destination name claimed by more than one capability.

    Args:
        selection: Resolved selection with its namespace report.

    Returns:
        Informational report entries; conflicts are selection errors.
    """
    return [
        Finding(
            "collision.shared-name",
            f"{role}/{name}",
            "Claimed by " + ", ".join(owners),
            Severity.INFO,
        )
        for role, name, owners in selection.namespace
        if len(owners) > 1
    ]


def exports(
    *,
    consumer: Manifest,
    inventory: Inventory,
    selection: SelectionResult,
    roots: Mapping[str, Path],
    dangling: Iterable[Finding],
) -> list[Finding]:
    """Fail exports that name nothing, or name content this repository never imports.

    Args:
        consumer: Validated consumer manifest.
        inventory: Candidate inventory, including consumer-vetoed records.
        selection: Selection after include/exclude, denies and overrides.
        roots: Available vendor trees by alias.
        dangling: Manifest ``dangling-export`` diagnostics.

    Returns:
        Export errors, or warnings where unavailable vendor inputs prevent a check.
    """
    publisher = consumer.publisher.id
    unavailable = sorted(
        vendor.id
        for vendor in consumer.vendors
        if vendor.mapping is None and vendor.id not in roots
    )
    findings: list[Finding] = []
    reported = set()
    for item in dangling:
        reported.add(item.location)
        if unavailable:
            findings.append(
                Finding(
                    "export.unverifiable",
                    item.location,
                    f"{item.message}; vendor input(s) {', '.join(unavailable)} "
                    "unavailable, run `ai-skills-engine lock --fetch`",
                    Severity.WARNING,
                )
            )
        else:
            findings.append(Finding("export.not-imported", item.location, item.message))
    mapped = {vendor.id for vendor in consumer.vendors if vendor.mapping is not None}
    records: tuple[Capability | Resource, ...] = (
        *inventory.capabilities,
        *inventory.resources,
    )
    candidates = {str(item.id) for item in records} | {
        str(item) for item in inventory.rejected
    }
    selected = {
        item.id
        for item in (*selection.capabilities, *selection.resources)
        if item.state in _SELECTED
    }
    for index, value in enumerate(consumer.exports):
        qualified = value if "/" in value else f"{publisher}/{value}"
        owner = qualified.split("/", 1)[0]
        location = f"/exports/{index}"
        if location in reported:
            continue
        vendor_input = owner in mapped and owner not in roots
        manifest_input = owner not in mapped and bool(unavailable)
        if owner != publisher and (vendor_input or manifest_input):
            continue  # Unavailable vendor inputs are reported by inventory.
        members = {
            key for key in candidates if matches(selector=qualified, identity=key)
        }
        if not members:
            findings.append(
                Finding(
                    "export.matches-nothing",
                    location,
                    f"Export {value} matches no capability or resource",
                )
            )
        elif not members & selected:
            findings.append(
                Finding(
                    "export.not-imported",
                    location,
                    f"Export {value} names content that is not imported: every "
                    "match is excluded by include/exclude, a deny or an override",
                )
            )
    return findings
