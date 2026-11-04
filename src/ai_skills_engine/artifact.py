"""Build deterministic package artifacts from selected inventory and provenance."""

import json
from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ai_skills_engine.artifacts.format import (
    ARTIFACT_FORMAT,
    Files,
    canonical_json,
    canonical_tar,
    digest,
    files_digest,
)
from ai_skills_engine.artifacts.index import build_index
from ai_skills_engine.artifacts.legal import legal_files
from ai_skills_engine.artifacts.materialize import (
    capability_path,
    lineage_json,
    materialize,
    resource_files,
)
from ai_skills_engine.artifacts.references import validate_artifact_references
from ai_skills_engine.artifacts.snapshot import (
    publications,
    record_source,
)
from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.model import Inventory
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.inventory.roles import inspect_role
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.registry.safe_tree import (
    install_directory,
)
from ai_skills_engine.selection.closure import closure
from ai_skills_engine.selection.cycles import strongly_connected
from ai_skills_engine.selection.load import load_inputs
from ai_skills_engine.selection.model import SelectionResult
from ai_skills_engine.selection.state import State

DIGEST_FILENAME = "artifact-digests.json"


def _selected(selection: SelectionResult) -> set[str]:
    """Read resolver decisions without selecting or resolving another graph.

    Args:
        selection: Authoritative consumer selection result.

    Returns:
        Selected and required capability/resource identities.

    Raises:
        ValueError: For any retained resolver error.
    """
    if not selection.valid:
        errors = [
            f"{item.code} {item.location}: {item.message}"
            for item in selection.diagnostics
            if not item.warning
        ]
        raise ValueError("Artifact selection failed:\n" + "\n".join(errors))
    return {
        item.id
        for item in (*selection.capabilities, *selection.resources)
        if item.state in {State.SELECTED, State.PULLED_IN}
    }


def artifact_name(package: str) -> str:
    """Map a qualified package ID injectively to its transport filename.

    Args:
        package: Qualified package ID.

    Returns:
        Canonical uncompressed tar filename.
    """
    return package.replace("/", "--") + ".tar"


def write_artifacts(
    *,
    inventory: Inventory,
    selection: SelectionResult,
    root: Path,
    vendor_roots: Mapping[str, Path],
    destination: Path,
    engine_version: str | None = None,
) -> dict[str, Any]:
    """Write every selected package in one transaction from complete engine inputs.

    Dependencies and SCCs use the existing selection algorithms. No dependency is
    inferred from a filename, prose or link. Copies are never deduplicated.

    Args:
        inventory: Complete inventory from the same pinned observation as selection.
        selection: Authoritative resolver output, including consumer vetoes.
        root: Consumer repository.
        vendor_roots: Explicit locally available pinned snapshots.
        destination: Artifact directory to replace only after every package succeeds.
        engine_version: Explicit builder identity for reproducibility fixtures.

    Returns:
        Generated committed-digest document, including external tar identities.

    Raises:
        ValueError: For invalid selection, stale observations or malformed output.
    """
    selected = _selected(selection)
    caps = {
        str(item.id): item
        for item in inventory.capabilities
        if str(item.id) in selected
    }
    resources = {
        str(item.id): item for item in inventory.resources if str(item.id) in selected
    }
    entries = {
        item.id: item
        for item in (*selection.capabilities, *selection.resources)
        if item.id in selected
    }
    observed_records: dict[str, Capability | Resource] = {**caps, **resources}
    if selected != caps.keys() | resources.keys() or any(
        entries[key].lineage != item.lineage for key, item in observed_records.items()
    ):
        raise ValueError("Artifact inventory and selection observations disagree")
    snapshots = publications(root=root, vendor_roots=vendor_roots)
    sources = {
        key: record_source(record=item, snapshots=snapshots)
        for key, item in observed_records.items()
    }
    graph = {
        key: tuple(sorted(map(str, (*item.requires, *item.resources))))
        for key, item in caps.items()
    }
    if any(target not in selected for targets in graph.values() for target in targets):
        raise ValueError("Selected artifact has an unavailable declared requirement")
    components = tuple(
        sorted(
            tuple(sorted(component))
            for component in strongly_connected(
                {key: tuple(map(str, item.requires)) for key, item in caps.items()}
            )
        )
    )
    files: Files = {}
    records: list[dict[str, Any]] = []
    resource_records: list[dict[str, Any]] = []
    closures: dict[str, set[str]] = {}
    document = read_document(root / "ai-skills.yaml")
    builder = engine_version if engine_version is not None else version("ai-skills")
    if any(path.is_symlink() for path in (destination, *destination.parents)):
        raise ValueError("Symlink rejected in artifact output path")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".artifacts-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "output"
        staged.mkdir()
        for key, resource in sorted(resources.items()):
            payload = resource_files(resource=resource, source=sources[key])
            path = f"packages/{resource.id.package}/resource/{resource.id.name}"
            files.update(
                {path + "/" + relative: value for relative, value in payload.items()}
            )
            resource_records.append(
                {
                    "id": key,
                    "path": path,
                    "treeDigest": files_digest(payload),
                    "sourceTreeDigest": "sha256:" + resource.tree_digest,
                    "lineage": lineage_json(resource.lineage),
                }
            )
        for key, capability in sorted(caps.items()):
            required = tuple(
                (resources[str(target)], sources[str(target)])
                for target in capability.resources
            )
            payload, copies, portability = materialize(
                capability=capability, source=sources[key], resources=required
            )
            path = capability_path(capability)
            files.update(
                {path + "/" + relative: value for relative, value in payload.items()}
            )
            # ADR 0006 validation is run on the isolated capability root itself.
            check_root = Path(temporary) / "links" / path
            for relative, (data, _mode) in payload.items():
                target = check_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            if not portability:
                validate_artifact_references(root=check_root)
            closure_ids = set(closure(graph=graph, roots=(key,), blocked=set()))
            closures[key] = closure_ids
            legal, licenses = legal_files(
                records=(capability, *(item for item, _ in required)),
                snapshots=snapshots,
            )
            origin = capability.lineage[0].lineage[0].origin
            _dialect, metadata = inspect_role(source=sources[key], role=capability.role)
            records.append(
                {
                    "id": key,
                    "package": str(capability.package),
                    "role": str(capability.role),
                    "dialect": str(capability.dialect),
                    "path": path,
                    "treeDigest": files_digest(payload),
                    "sourceTreeDigest": "sha256:" + capability.tree_digest,
                    "requires": sorted(map(str, capability.requires)),
                    "related": sorted(map(str, capability.related)),
                    "closure": {
                        "capabilities": sorted(closure_ids & caps.keys()),
                        "resources": sorted(closure_ids & resources.keys()),
                        "units": [
                            list(component)
                            for component in components
                            if set(component).issubset(closure_ids)
                        ],
                    },
                    "resources": copies,
                    "lineage": lineage_json(capability.lineage),
                    "license": str(
                        metadata.get("license", licenses.get(origin, "NOASSERTION"))
                    ),
                    "notices": sorted(legal),
                    "portability": portability,
                    "names": list(entries[key].names),
                    "aliases": list(capability.aliases),
                    "hostAttributes": [
                        {
                            "key": item.key,
                            "value": json.loads(item.value_json),
                            "semantics": item.semantics,
                            "hosts": dict(item.hosts),
                        }
                        for item in capability.host_attributes
                    ],
                    "executionSurface": (
                        json.loads(payload[sources[key].name][0])
                        if capability.role in {"lifecycle", "integration"}
                        else {}
                    ),
                }
            )
        all_records: tuple[Capability | Resource, ...] = (
            *caps.values(),
            *resources.values(),
        )
        legal, _licenses = legal_files(records=all_records, snapshots=snapshots)
        catalog = build_index(
            records=records,
            resource_records=resource_records,
            files={**files, **legal},
            snapshots=snapshots,
            api_version=document["apiVersion"],
            engine_version=builder,
            root_package=None,
        )
        (staged / "index.json").write_bytes(canonical_json(catalog))
        expected: dict[str, Any] = {"artifactFormat": ARTIFACT_FORMAT, "packages": {}}
        for package in catalog["packages"]:
            package_id = package["id"]
            members = {
                target
                for item in package["capabilities"]
                for target in closures[item["id"]]
            }
            members.update(item["id"] for item in package["resources"])
            included = [item for item in records if item["id"] in members]
            included_resources = [
                item for item in resource_records if item["id"] in members
            ]
            paths = tuple(
                item["path"] + "/" for item in (*included, *included_resources)
            )
            payload = {
                path: value for path, value in files.items() if path.startswith(paths)
            }
            obligations, _ = legal_files(
                records=tuple(
                    item for key, item in observed_records.items() if key in members
                ),
                snapshots=snapshots,
            )
            payload.update(obligations)
            index = build_index(
                records=included,
                resource_records=included_resources,
                files=payload,
                snapshots=snapshots,
                api_version=document["apiVersion"],
                engine_version=builder,
                root_package=package_id,
            )
            tree = package["treeDigest"]
            payload["index.json"] = (canonical_json(index), 0o644)
            tar = canonical_tar(payload)
            name = artifact_name(package_id)
            (staged / name).write_bytes(tar)
            (staged / (name + ".sha256")).write_text(
                f"{digest(tar)[7:]}  {name}\n", encoding="utf-8"
            )
            expected["packages"][package_id] = {
                "treeDigest": tree,
                "artifactDigest": digest(tar),
            }
        install_directory(source=staged, destination=destination)
    return expected


def build(
    *,
    root: Path,
    vendor_roots: Mapping[str, Path] | None = None,
    destination: Path | None = None,
) -> dict[str, Any]:
    """Build offline from manifest-pinned, explicitly available source inputs.

    Args:
        root: Consumer/publisher root.
        vendor_roots: Explicit pinned input snapshots.
        destination: Output override, defaulting to dist/artifacts/.

    Returns:
        Complete generated digest document.
    """
    roots = vendor_roots or {}
    inventory, selection = load_inputs(root, vendor_roots=roots)
    return write_artifacts(
        inventory=inventory,
        selection=selection,
        root=root,
        vendor_roots=roots,
        destination=destination or root / "dist/artifacts",
    )
