"""Pure deltas between two resolved artifact indexes, scoped to one vendor.

Nothing here infers identity from content. Capabilities are compared by their
stable qualified ID; a declared migration is the only way two different IDs are
reported as one renamed capability.
"""

from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import quote

from ai_skills_engine.repin.catalog_side import CatalogSide
from ai_skills_engine.repin.change import Change

# Lineage hop fields that move with every revision bump and are reported
# through the pin and digest sections instead.
_VOLATILE_HOP_FIELDS = frozenset({"rev", "treeDigest"})
_IGNORED_RECORD_FIELDS = frozenset({"lineage", "resources", "closure"})
_RENAME_FIELDS = frozenset({"id", "names", "path", "closure", "lineage"})


def vendor_index(
    index: Mapping[str, Any], *, publisher: str, origin: str
) -> dict[str, Any]:
    """Restrict a catalog index to one vendor's packages and legal files.

    A package belongs to the vendor when its ID is in the vendor's publisher
    namespace or any of its records names the vendor's origin in lineage.

    Args:
        index: Complete catalog index.
        publisher: Publisher namespace of the vendor.
        origin: Lineage origin locator, for example ``github.com/owner/repo``.

    Returns:
        Index-shaped mapping with only the vendor's packages and legal files.
    """
    packages = [
        package
        for package in index.get("packages", ())
        if package["id"].startswith(publisher + "/")
        or any(
            hop.get("origin") == origin
            for record in (*package["capabilities"], *package["resources"])
            for chain in record.get("lineage", ())
            for hop in chain.get("lineage", ())
        )
    ]
    license_path = "LICENSES/" + quote(origin, safe="") + ".txt"
    return {
        **index,
        "packages": packages,
        "legalFiles": [
            item
            for item in index.get("legalFiles", ())
            if item["path"] in {license_path, "NOTICE.md"}
        ],
    }


def revision_free_legal(
    index: Mapping[str, Any], legal: Mapping[str, str]
) -> dict[str, Any]:
    """Replace legal-file digests with their revision-free content digests.

    The generated ``LICENSES/<origin>.txt`` header names the pinned revision, so
    its raw index digest moves on every pin bump. Both the SemVer advice and the
    license section compare the digests returned here instead.

    Args:
        index: Catalog index.
        legal: Legal path to revision-free content digest of the same build.

    Returns:
        Index-shaped mapping; paths absent from ``legal`` keep their digest.
    """
    return {
        **index,
        "legalFiles": [
            {**item, "digest": legal.get(item["path"], item["digest"])}
            for item in index.get("legalFiles", ())
        ],
    }


def capabilities(index: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten capability records by qualified ID.

    Args:
        index: Resolved index.

    Returns:
        Capability records keyed by ID.
    """
    return {
        item["id"]: item
        for package in index.get("packages", ())
        for item in package["capabilities"]
    }


def resources(index: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten standalone package resources by qualified ID.

    Args:
        index: Resolved index.

    Returns:
        Resource records keyed by ID.
    """
    return {
        item["id"]: item
        for package in index.get("packages", ())
        for item in package["resources"]
    }


def _stable_lineage(record: Mapping[str, Any]) -> list[Any]:
    """Drop the revision-bound hop fields from a lineage list.

    Args:
        record: Capability or resource record.

    Returns:
        Lineage chains without per-revision fields.
    """
    return [
        {
            **chain,
            "lineage": [
                {
                    key: value
                    for key, value in hop.items()
                    if key not in _VOLATILE_HOP_FIELDS
                }
                for hop in chain.get("lineage", ())
            ],
        }
        for chain in record.get("lineage", ())
    ]


def stable_index(index: Mapping[str, Any]) -> dict[str, Any]:
    """Drop revision-bound lineage fields so a bare pin bump is not a change.

    Legal digests are expected to be revision-free already
    (:func:`revision_free_legal`).

    Args:
        index: Vendor-scoped index.

    Returns:
        Index-shaped mapping for advisory comparison.
    """
    return {
        **index,
        "packages": [
            {
                **package,
                "capabilities": [
                    {**item, "lineage": _stable_lineage(item)}
                    for item in package["capabilities"]
                ],
                "resources": [
                    {**item, "lineage": _stable_lineage(item)}
                    for item in package["resources"]
                ],
            }
            for package in index.get("packages", ())
        ],
    }


def _changed_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    """Name the record fields whose values differ.

    Args:
        before: Previous record.
        after: Current record.

    Returns:
        Sorted field names; lineage counts only for stable changes.
    """
    fields = sorted(
        key
        for key in before.keys() | after.keys()
        if key not in _IGNORED_RECORD_FIELDS and before.get(key) != after.get(key)
    )
    if _stable_lineage(before) != _stable_lineage(after):
        fields.append("lineage")
    if [item.get("id") for item in before.get("resources", ())] != [
        item.get("id") for item in after.get("resources", ())
    ] or [item.get("treeDigest") for item in before.get("resources", ())] != [
        item.get("treeDigest") for item in after.get("resources", ())
    ]:
        fields.append("resources")
    if before.get("closure") != after.get("closure"):
        fields.append("closure")
    return sorted(fields)


def capability_changes(
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    renames: Mapping[str, tuple[str, str]],
) -> tuple[tuple[Change, ...], dict[str, str]]:
    """List added, removed, changed and declared-renamed capabilities.

    Args:
        before: Vendor-scoped previous index.
        after: Vendor-scoped current index.
        renames: Declared migrations, old ID to (new ID, declaring source).

    Returns:
        Sorted changes and the applied rename pairs (old to new ID).
    """
    old, new = capabilities(before), capabilities(after)
    applied = {
        source: target
        for source, (target, _origin) in renames.items()
        if source in old and target in new and source not in new
    }
    lines = [
        Change(
            subject=source,
            kind="renamed",
            detail=f"{target} ({renames[source][1]})",
        )
        for source, target in applied.items()
    ]
    lines.extend(
        Change(subject=key, kind="added", detail=new[key]["role"])
        for key in new.keys() - old.keys() - set(applied.values())
    )
    lines.extend(
        Change(subject=key, kind="removed", detail=old[key]["role"])
        for key in old.keys() - new.keys() - applied.keys()
    )
    for key in old.keys() & new.keys():
        fields = _changed_fields(old[key], new[key])
        if fields:
            lines.append(
                Change(
                    subject=key,
                    kind="changed",
                    detail=f"{new[key]['role']}: {', '.join(fields)}",
                )
            )
    for source, target in applied.items():
        fields = _changed_fields(old[source], new[target])
        # Identity-bound fields necessarily differ; the lineage section reports
        # the source move.
        fields = [field for field in fields if field not in _RENAME_FIELDS]
        if fields:
            lines.append(
                Change(
                    subject=target,
                    kind="changed",
                    detail=f"{new[target]['role']}: {', '.join(fields)}",
                )
            )
    return tuple(sorted(lines)), applied


def identical_moves(
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    applied: Mapping[str, str],
) -> tuple[Change, ...]:
    """Report undeclared identical-content moves without ever applying them.

    Args:
        before: Vendor-scoped previous index.
        after: Vendor-scoped current index.
        applied: Declared renames already applied.

    Returns:
        ``removed ID -> added ID`` pairs whose source trees are equal.
    """
    old, new = capabilities(before), capabilities(after)
    removed = old.keys() - new.keys() - applied.keys()
    added = new.keys() - old.keys() - set(applied.values())
    return tuple(
        sorted(
            Change(subject=source, kind="identical-content", detail=target)
            for source in removed
            for target in added
            if old[source]["sourceTreeDigest"] == new[target]["sourceTreeDigest"]
        )
    )


def _members(files: Mapping[str, str], prefix: str) -> dict[str, str]:
    """Select artifact members below a record directory.

    Args:
        files: Member path to digest.
        prefix: Record output path.

    Returns:
        Relative member path to digest.
    """
    start = prefix.rstrip("/") + "/"
    return {
        path[len(start) :]: value
        for path, value in files.items()
        if path.startswith(start)
    }


def file_changes(
    *,
    before: CatalogSide,
    after: CatalogSide,
    applied: Mapping[str, str],
) -> tuple[Change, ...]:
    """List ``+``/``-``/``~`` files for every changed or renamed capability.

    Args:
        before: Previous catalog.
        after: Current catalog.
        applied: Declared renames already applied.

    Returns:
        Sorted file deltas keyed by the current capability ID.
    """
    old, new = capabilities(before.index), capabilities(after.index)
    pairs = [(key, key) for key in sorted(old.keys() & new.keys())]
    pairs.extend(sorted(applied.items()))
    lines: list[Change] = []
    for source, target in pairs:
        previous = _members(before.files, old[source]["path"])
        current = _members(after.files, new[target]["path"])
        lines.extend(
            Change(subject=target, kind="+", detail=path)
            for path in current.keys() - previous.keys()
        )
        lines.extend(
            Change(subject=target, kind="-", detail=path)
            for path in previous.keys() - current.keys()
        )
        lines.extend(
            Change(subject=target, kind="~", detail=path)
            for path in previous.keys() & current.keys()
            if previous[path] != current[path]
        )
    return tuple(sorted(lines))


def resource_changes(
    *, before: Mapping[str, Any], after: Mapping[str, Any]
) -> tuple[Change, ...]:
    """List standalone resource additions, removals and content changes.

    Args:
        before: Vendor-scoped previous index.
        after: Vendor-scoped current index.

    Returns:
        Sorted resource deltas.
    """
    old, new = resources(before), resources(after)
    lines = [Change(subject=key, kind="added") for key in new.keys() - old.keys()]
    lines.extend(Change(subject=key, kind="removed") for key in old.keys() - new.keys())
    lines.extend(
        Change(
            subject=key,
            kind="changed",
            detail=", ".join(_changed_fields(old[key], new[key])),
        )
        for key in old.keys() & new.keys()
        if _changed_fields(old[key], new[key])
    )
    return tuple(sorted(lines))


def _origin_path(record: Mapping[str, Any]) -> str:
    """Return the first-hop source path of a record.

    Args:
        record: Capability or resource record.

    Returns:
        Upstream source path, or an empty string without lineage.
    """
    for chain in record.get("lineage", ()):
        for hop in chain.get("lineage", ()):
            return str(hop.get("path") or "")
    return ""


def lineage_changes(
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    applied: Mapping[str, str],
) -> tuple[Change, ...]:
    """List lineage changes beyond the revision bump, including source moves.

    Args:
        before: Vendor-scoped previous index.
        after: Vendor-scoped current index.
        applied: Declared renames already applied.

    Returns:
        Sorted lineage deltas.
    """
    old = {**capabilities(before), **resources(before)}
    new = {**capabilities(after), **resources(after)}
    pairs = [(key, key) for key in old.keys() & new.keys()]
    pairs.extend(applied.items())
    lines = []
    for source, target in pairs:
        if _stable_lineage(old[source]) == _stable_lineage(new[target]):
            continue
        previous, current = _origin_path(old[source]), _origin_path(new[target])
        detail = (
            f"path {previous} -> {current}"
            if previous != current
            else "provenance chain changed"
        )
        lines.append(Change(subject=target, kind="changed", detail=detail))
    return tuple(sorted(lines))


def source_moves(
    *, before: Mapping[str, Any], after: Mapping[str, Any]
) -> tuple[tuple[str, str, str], ...]:
    """Find capabilities whose declared ID stayed while their source path moved.

    Args:
        before: Vendor-scoped previous index.
        after: Vendor-scoped current index.

    Returns:
        Sorted ``(id, old path, new path)`` triples.
    """
    old, new = capabilities(before), capabilities(after)
    return tuple(
        sorted(
            (key, _origin_path(old[key]), _origin_path(new[key]))
            for key in old.keys() & new.keys()
            if _origin_path(old[key]) != _origin_path(new[key])
        )
    )


def legal_changes(
    *, before: Mapping[str, Any], after: Mapping[str, Any]
) -> tuple[Change, ...]:
    """List license and notice changes.

    Args:
        before: Vendor-scoped previous index.
        after: Vendor-scoped current index.

    Returns:
        Sorted legal-file and capability license deltas.
    """
    old = {item["path"]: item["digest"] for item in before.get("legalFiles", ())}
    new = {item["path"]: item["digest"] for item in after.get("legalFiles", ())}
    lines = [Change(subject=path, kind="added") for path in new.keys() - old.keys()]
    lines.extend(
        Change(subject=path, kind="removed") for path in old.keys() - new.keys()
    )
    lines.extend(
        Change(subject=path, kind="changed")
        for path in old.keys() & new.keys()
        if old[path] != new[path]
    )
    previous, current = capabilities(before), capabilities(after)
    lines.extend(
        Change(
            subject=key,
            kind="license",
            detail=f"{previous[key]['license']} -> {current[key]['license']}",
        )
        for key in previous.keys() & current.keys()
        if previous[key]["license"] != current[key]["license"]
    )
    return tuple(sorted(lines))


def _package_digests(
    index: Mapping[str, Any], artifacts: Mapping[str, str]
) -> dict[str, tuple[str, str]]:
    """Read package tree and artifact digests.

    Args:
        index: Vendor-scoped index.
        artifacts: Package ID to tar digest.

    Returns:
        Package ID to ``(treeDigest, artifactDigest)``.
    """
    return {
        package["id"]: (package["treeDigest"], artifacts.get(package["id"], ""))
        for package in index.get("packages", ())
    }


def digest_changes(
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    before_artifacts: Mapping[str, str],
    after_artifacts: Mapping[str, str],
) -> tuple[Change, ...]:
    """List every vendor package's tree and artifact digests, old to new.

    Args:
        before: Vendor-scoped previous index.
        after: Vendor-scoped current index.
        before_artifacts: Previous tar digests.
        after_artifacts: Current tar digests.

    Returns:
        Sorted digest lines; ``none`` marks an absent side.
    """
    old = _package_digests(before, before_artifacts)
    new = _package_digests(after, after_artifacts)
    lines = []
    for package in old.keys() | new.keys():
        for position, field in enumerate(("treeDigest", "artifactDigest")):
            previous = old[package][position] if package in old else "none"
            current = new[package][position] if package in new else "none"
            lines.append(
                Change(
                    subject=package,
                    kind=field,
                    detail=(
                        f"{previous} (unchanged)"
                        if previous == current
                        else f"{previous} -> {current}"
                    ),
                )
            )
    return tuple(sorted(lines))


def capability_count(index: Mapping[str, Any]) -> int:
    """Count capabilities in a scoped index.

    Args:
        index: Vendor-scoped index.

    Returns:
        Number of capabilities.
    """
    return len(capabilities(index))


def covered_paths(index: Mapping[str, Any], *, origin: str) -> frozenset[str]:
    """Collect upstream source paths delivered from one origin.

    Args:
        index: Vendor-scoped index.
        origin: Vendor lineage origin locator.

    Returns:
        First-hop source paths of the vendor's capabilities.
    """
    return frozenset(
        hop["path"]
        for record in capabilities(index).values()
        for chain in record.get("lineage", ())
        for hop in chain.get("lineage", ())[:1]
        if hop.get("origin") == origin and hop.get("path")
    )


def uncovered(skill_dirs: Iterable[str], covered: frozenset[str]) -> frozenset[str]:
    """Return skill directories not delivered by, or nested in, a capability.

    Args:
        skill_dirs: Upstream directories containing ``SKILL.md``.
        covered: Delivered upstream source paths.

    Returns:
        Uncovered skill directories.
    """
    return frozenset(
        path
        for path in skill_dirs
        if path not in covered
        and not any(path.startswith(item + "/") for item in covered)
    )
