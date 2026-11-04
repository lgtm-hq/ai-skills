"""Generate host plugin envelopes from a resolved artifact index.

Every native envelope (``plugin.json``, ``.claude-plugin``, ``.cursor-plugin``
and ``.codex-plugin`` manifests plus the Claude, Cursor and Codex marketplaces)
comes from one generator. The artifact index is the only capability input:
roles, versions, tree digests, ``_shared`` resource copies and closures are
read from it, never from legacy registries or source trees. Presentation
metadata (display names, descriptions, authors and licenses) is supplied by
the caller from the publishing manifest. The field rules are data in
``envelope-rules.v1.json`` so the install plane can regenerate filtered
envelopes byte for byte.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum, auto
from functools import cache

# nosemgrep: python37-compatibility-importlib2 - runtime requires Python >=3.13
from importlib import resources
from pathlib import Path
from typing import Any

RULES_NAME = "envelope-rules.v1.json"
_SKILLS_DIRECTORY = "./skills/"
_SERIALIZATION = {
    "indent": 2,
    "ensureAscii": False,
    "sortKeys": False,
    "trailingNewline": True,
}


class Host(StrEnum):
    """Hosts with a generated native envelope."""

    CLAUDE = auto()
    CODEX = auto()
    CURSOR = auto()


ALL_HOSTS = frozenset(Host)


class Layout(StrEnum):
    """How marketplace entries locate their plugin payload."""

    SLICE = auto()
    BUILT = auto()


class EnvelopeError(ValueError):
    """An envelope cannot represent the requested capabilities without loss."""


@dataclass(frozen=True)
class SliceSource:
    """An in-repo capability tree that a repo-root marketplace may reference.

    Attributes:
        path: Repository-relative POSIX source path.
        tree_digest: Qualified digest of the in-repo bytes and modes.
    """

    path: str
    tree_digest: str


@dataclass(frozen=True)
class PackageEnvelope:
    """Presentation metadata for one published package.

    Attributes:
        package: Qualified package ID in the artifact index.
        plugin: Host plugin name.
        display_name: Human-readable plugin name.
        description: Marketplace entry description.
        plugin_description: Per-plugin envelope description.
        author: Author name stamped onto per-plugin envelopes.
        license: Declared license, omitted from envelopes when unknown.
        slices: Capability ID to in-repo source for the slice layout.
    """

    package: str
    plugin: str
    display_name: str
    description: str
    plugin_description: str
    author: str
    license: str | None = None
    slices: Mapping[str, SliceSource] | None = None


@dataclass(frozen=True)
class Marketplace:
    """Marketplace identity and payload layout.

    Attributes:
        name: Marketplace registration name.
        owner: Owner name.
        description: Catalog description for hosts with metadata.
        version: Repository version for metadata and in-repo slice entries.
        notice: Do-not-edit marker for hosts whose schema allows it.
        layout: In-repo slices or built per-plugin directories.
        plugin_root: Built-layout prefix for plugin directories.
    """

    name: str
    owner: str
    description: str
    version: str
    notice: str
    layout: Layout
    plugin_root: str = ""


@dataclass(frozen=True)
class _Plugin:
    """One package after filtering, ready for rendering."""

    package: PackageEnvelope
    version: str
    skills: tuple[str, ...]


@cache
def rules() -> dict[str, Any]:
    """Read and check the envelope rules shipped with the installed engine.

    Returns:
        Parsed rule document.

    Raises:
        EnvelopeError: If the shipped rules do not match this generator.
    """
    document = json.loads(
        resources.files("ai_skills_engine.data")
        .joinpath(RULES_NAME)
        .read_text(encoding="utf-8")
    )
    if (
        not isinstance(document, dict)
        or document.get("rulesVersion") != 1
        or document.get("serialization") != _SERIALIZATION
        or set(document.get("hosts", {})) != {str(host) for host in Host}
    ):
        raise EnvelopeError(f"Unsupported envelope rules: {RULES_NAME}")
    return document


def render(payload: Mapping[str, Any]) -> bytes:
    """Serialize one envelope with the shared deterministic JSON rules.

    Args:
        payload: Ordered JSON-compatible mapping.

    Returns:
        UTF-8 JSON with two-space indentation and a trailing newline.
    """
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode()


def _host_order(hosts: Iterable[Host]) -> tuple[Host, ...]:
    """Return requested hosts in a stable order.

    Args:
        hosts: Requested hosts.

    Returns:
        Unique hosts in declaration order.
    """
    requested = set(hosts)
    return tuple(host for host in Host if host in requested)


def require_projection(*, capability: str, role: str, hosts: Iterable[Host]) -> None:
    """Fail when a host has no envelope projection for a capability's role.

    Args:
        capability: Qualified capability ID named in the error.
        role: Capability role.
        hosts: Hosts that must project the role.

    Raises:
        EnvelopeError: If any host lacks a projection.
    """
    for host in _host_order(hosts):
        if role not in rules()["hosts"][host]["roles"]:
            raise EnvelopeError(
                f"{capability}: role {role!r} has no {host} envelope projection; "
                "exclude it or add a host projection"
            )


def _plugin_value(*, field: str, package: PackageEnvelope, version: str) -> Any:
    """Resolve one per-plugin envelope field.

    Args:
        field: Rule field name.
        package: Package presentation.
        version: Artifact package version.

    Returns:
        JSON value.

    Raises:
        EnvelopeError: For a field outside the rule vocabulary.
    """
    values: dict[str, Any] = {
        "name": package.plugin,
        "version": version,
        "description": package.plugin_description,
        "author": {"name": package.author},
        "displayName": package.display_name,
        "license": package.license,
        "skills": _SKILLS_DIRECTORY,
    }
    if field not in values:
        raise EnvelopeError(f"Unknown plugin envelope field: {field}")
    return values[field]


def _plugin_payload(
    *, fields: Sequence[str], package: PackageEnvelope, version: str
) -> dict[str, Any]:
    """Build one per-plugin envelope, omitting an unknown license.

    Args:
        fields: Ordered rule fields.
        package: Package presentation.
        version: Artifact package version.

    Returns:
        Ordered envelope mapping.
    """
    payload: dict[str, Any] = {}
    for field in fields:
        value = _plugin_value(field=field, package=package, version=version)
        if field == "license" and value is None:
            continue
        payload[field] = value
    return payload


def plugin_envelopes(
    *,
    package: PackageEnvelope,
    version: str,
    roles: Iterable[tuple[str, str]],
    hosts: Iterable[Host],
) -> dict[str, bytes]:
    """Render the per-plugin envelopes for one plugin directory.

    Skills and specialists are projected through the host-discovered
    ``skills/`` and ``agents/`` directories, so the envelopes reference the
    delivered (already filtered) tree rather than enumerating it.

    Args:
        package: Package presentation.
        version: Artifact package version.
        roles: ``(capability ID, role)`` pairs delivered in this plugin.
        hosts: Hosts receiving an envelope.

    Returns:
        Plugin-relative POSIX path to exact bytes.
    """
    selected = _host_order(hosts)
    for capability, role in roles:
        require_projection(capability=capability, role=role, hosts=selected)
    document = rules()
    files = {
        document["plugin"]["path"]: render(
            _plugin_payload(
                fields=document["plugin"]["fields"], package=package, version=version
            )
        )
    }
    for host in selected:
        plugin = document["hosts"][host]["plugin"]
        files[plugin["path"]] = render(
            _plugin_payload(fields=plugin["fields"], package=package, version=version)
        )
    return files


def _source(*, host: Host, marketplace: Marketplace, plugin: str) -> Any:
    """Return a marketplace entry's payload location.

    Args:
        host: Marketplace host.
        marketplace: Marketplace identity and layout.
        plugin: Plugin name.

    Returns:
        Path string or host-specific source object.
    """
    path = (
        "./"
        if marketplace.layout is Layout.SLICE
        else f"./{marketplace.plugin_root}{plugin}"
    )
    if rules()["hosts"][host]["marketplace"]["source"] == "local":
        return {"source": "local", "path": path}
    return path


def _entry(*, host: Host, marketplace: Marketplace, plugin: _Plugin) -> dict[str, Any]:
    """Build one marketplace plugin entry.

    Args:
        host: Marketplace host.
        marketplace: Marketplace identity and layout.
        plugin: Filtered package.

    Returns:
        Ordered entry mapping.

    Raises:
        EnvelopeError: For a field outside the rule vocabulary.
    """
    spec = rules()["hosts"][host]["marketplace"]
    package = plugin.package
    entry: dict[str, Any] = {}
    for field in spec["entries"][marketplace.layout]:
        match field:
            case "name":
                entry[field] = package.plugin
            case "displayName":
                entry[field] = package.display_name
            case "description":
                entry[field] = package.description
            case "version":
                entry[field] = plugin.version
            case "source":
                entry[field] = _source(
                    host=host, marketplace=marketplace, plugin=package.plugin
                )
            case "strict":
                entry[field] = False
            case "skills":
                entry[field] = [f"./{path}" for path in plugin.skills]
            case "policy":
                entry[field] = dict(spec["policy"])
            case _:
                raise EnvelopeError(f"Unknown marketplace entry field: {field}")
    return entry


def _marketplace(
    *, host: Host, marketplace: Marketplace, plugins: Sequence[_Plugin]
) -> bytes:
    """Render one host marketplace.

    Args:
        host: Marketplace host.
        marketplace: Marketplace identity and layout.
        plugins: Filtered packages in catalog order.

    Returns:
        Exact marketplace bytes.

    Raises:
        EnvelopeError: For a field outside the rule vocabulary.
    """
    payload: dict[str, Any] = {}
    for field in rules()["hosts"][host]["marketplace"]["fields"]:
        match field:
            case "name":
                payload[field] = marketplace.name
            case "owner":
                payload[field] = {"name": marketplace.owner}
            case "$generated":
                payload[field] = marketplace.notice
            case "metadata":
                payload[field] = {
                    "description": marketplace.description,
                    "version": marketplace.version,
                    "$generated": marketplace.notice,
                }
            case "plugins":
                payload[field] = [
                    _entry(host=host, marketplace=marketplace, plugin=plugin)
                    for plugin in plugins
                ]
            case _:
                raise EnvelopeError(f"Unknown marketplace field: {field}")
    return render(payload)


def _slice_skills(
    *, package: PackageEnvelope, kept: Sequence[Mapping[str, Any]]
) -> tuple[str, ...]:
    """Prove each kept capability is byte-identical in its in-repo slice.

    Args:
        package: Package presentation with slice sources.
        kept: Kept index capability records.

    Returns:
        Sliced skill source paths in catalog order.

    Raises:
        EnvelopeError: If any capability needs a built envelope.
    """
    slices = package.slices or {}
    advice = f"package {package.package} needs a built envelope"
    for capability in kept:
        identity = capability["id"]
        source = slices.get(identity)
        if source is None or capability["role"] != "skill":
            raise EnvelopeError(f"{identity} has no in-repo skill slice; {advice}")
        if capability["resources"]:
            raise EnvelopeError(f"{identity} carries artifact-only resources; {advice}")
        if source.tree_digest != capability["treeDigest"]:
            raise EnvelopeError(
                f"{identity}: in-repo slice {source.path} differs from the "
                f"artifact tree {capability['treeDigest']}; {advice}"
            )
    kept_ids = {capability["id"] for capability in kept}
    return tuple(
        source.path for identity, source in slices.items() if identity in kept_ids
    )


def _keep_set(
    *, capabilities: Mapping[str, Mapping[str, Any]], keep: frozenset[str] | None
) -> frozenset[str]:
    """Validate the kept capability set against the index and its closures.

    Args:
        capabilities: Index capabilities by ID.
        keep: Kept IDs, or every indexed capability when None.

    Returns:
        Kept IDs.

    Raises:
        EnvelopeError: For unknown IDs or a kept capability missing a requirement.
    """
    kept = frozenset(capabilities) if keep is None else keep
    if unknown := sorted(kept - capabilities.keys()):
        raise EnvelopeError(f"Kept capability is not in the artifact: {unknown[0]}")
    for identity in sorted(kept):
        missing = sorted(set(capabilities[identity]["closure"]["capabilities"]) - kept)
        if missing:
            raise EnvelopeError(f"{identity} requires excluded capability {missing[0]}")
    return kept


def generate(
    index: Mapping[str, Any],
    keep: frozenset[str] | None,
    hosts: Iterable[Host],
    *,
    marketplace: Marketplace,
    packages: Sequence[PackageEnvelope],
) -> dict[str, bytes]:
    """Generate every envelope for the kept capabilities of published packages.

    A package whose capabilities are all excluded disappears from every
    envelope and marketplace. Slice-layout output contains marketplaces only;
    built-layout output also contains each plugin directory's envelopes.

    Args:
        index: Schema-valid artifact index.
        keep: Kept capability IDs; None keeps everything in the index.
        hosts: Hosts receiving envelopes.
        marketplace: Marketplace identity and layout.
        packages: Published packages in marketplace order.

    Returns:
        Relative POSIX path to exact bytes.

    Raises:
        EnvelopeError: For missing packages, unsupported roles, broken
            closures, colliding plugin names or unrepresentable slices.
    """
    # Deferred: artifact validation imports inventory, whose vendor bake
    # imports this module for the shared per-plugin envelopes.
    from ai_skills_engine.artifacts.format import validate_index

    validate_index(dict(index))
    selected = _host_order(hosts)
    indexed = {package["id"]: package for package in index["packages"]}
    capabilities = {
        capability["id"]: capability
        for package in index["packages"]
        for capability in package["capabilities"]
    }
    kept_ids = _keep_set(capabilities=capabilities, keep=keep)
    files: dict[str, bytes] = {}
    plugins: list[_Plugin] = []
    names: set[str] = set()
    for package in packages:
        if package.package not in indexed:
            raise EnvelopeError(f"Package {package.package} is not in the artifact")
        record = indexed[package.package]
        kept = [item for item in record["capabilities"] if item["id"] in kept_ids]
        if not kept:
            continue
        if package.plugin in names:
            raise EnvelopeError(f"Duplicate plugin name: {package.plugin}")
        names.add(package.plugin)
        roles = tuple((item["id"], item["role"]) for item in kept)
        for capability, role in roles:
            require_projection(capability=capability, role=role, hosts=selected)
        skills: tuple[str, ...] = ()
        if marketplace.layout is Layout.SLICE:
            skills = _slice_skills(package=package, kept=kept)
        else:
            prefix = f"{marketplace.plugin_root}{package.plugin}/"
            for relative, data in plugin_envelopes(
                package=package, version=record["version"], roles=roles, hosts=selected
            ).items():
                files[prefix + relative] = data
        # In-repo slices are served at the repository version, which the
        # VERSION/pyproject consistency check stamps; built trees carry the
        # artifact package version (pin-derived for vendors).
        version = (
            marketplace.version
            if marketplace.layout is Layout.SLICE
            else record["version"]
        )
        plugins.append(_Plugin(package=package, version=version, skills=skills))
    for host in selected:
        files[rules()["hosts"][host]["marketplace"]["path"]] = _marketplace(
            host=host, marketplace=marketplace, plugins=plugins
        )
    return files


def write_files(*, destination: Path, files: Mapping[str, bytes]) -> None:
    """Write generated envelopes below a destination directory.

    Args:
        destination: Directory receiving the relative paths.
        files: Relative POSIX path to exact bytes.

    Raises:
        EnvelopeError: If a target or its parent is a symlink.
    """
    for relative, data in files.items():
        path = destination / relative
        if any(item.is_symlink() for item in (path, *path.parents)):
            raise EnvelopeError(f"Symlink rejected in envelope path: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def stale_files(*, destination: Path, files: Mapping[str, bytes]) -> list[str]:
    """Describe every generated envelope that is missing or stale.

    Args:
        destination: Directory holding the relative paths.
        files: Relative POSIX path to expected bytes.

    Returns:
        Drift messages in generation order; empty when everything matches.
    """
    messages = []
    for relative in files:
        path = destination / relative
        if not path.is_file() or path.is_symlink():
            messages.append(f"Missing generated file: {path}")
        elif path.read_bytes() != files[relative]:
            messages.append(f"Generated file is stale: {path}")
    return messages


def check_files(*, destination: Path, files: Mapping[str, bytes]) -> None:
    """Require generated envelopes to match exactly.

    Args:
        destination: Directory holding the relative paths.
        files: Relative POSIX path to expected bytes.

    Raises:
        ValueError: For the first missing or stale envelope.
    """
    if messages := stale_files(destination=destination, files=files):
        raise ValueError(messages[0])
