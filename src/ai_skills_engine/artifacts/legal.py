"""License and notice obligations of actual shipped ancestry only."""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ai_skills_engine.artifacts.format import Files
from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.payload import source_path
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.provenance.context import origin_locator
from ai_skills_engine.registry.ingest_checks import (
    inspect_bytes,
    parse_allow,
    parse_limits,
    read_bounded,
)
from ai_skills_engine.registry.ingest_limits import DEFAULT_LIMITS
from ai_skills_engine.registry.registry import load_registry, render_notice
from ai_skills_engine.registry.safe_tree import iter_directory_entries

_LEGAL = re.compile(
    r"^(?:licen[cs]e|copying|copyright|notice)(?:[._-].*)?$", flags=re.IGNORECASE
)


def section_header(*, origin: str, revision: str | None, declared: str) -> str:
    """Render the header that opens one ``(origin, revision)`` legal section.

    ``repin.legal_text`` strips exactly the ``Revision:`` line of this header,
    so both sides share this single template.

    Args:
        origin: Origin locator.
        revision: Pinned revision, or None for the local publication.
        declared: Declared SPDX license.

    Returns:
        Three header lines.
    """
    return (
        f"Origin: {origin}\nRevision: {revision or 'local'}\n"
        f"Declared license: {declared}\n"
    )


def origin_file(origin: str) -> str:
    """Encode an origin injectively into a portable license filename.

    Args:
        origin: Complete origin locator, including repository namespace.

    Returns:
        License destination path.
    """
    return "LICENSES/" + quote(origin, safe=".-_") + ".txt"


def legal_files(
    *,
    records: tuple[Capability | Resource, ...],
    snapshots: Mapping[tuple[str, str | None], tuple[Path, dict[str, Any]]],
) -> tuple[Files, dict[str, str]]:
    """Propagate root and shipped-payload license/notice bytes across every hop.

    Args:
        records: Exactly the capabilities and resources present in an artifact.
        snapshots: Bound local or pinned publication metadata.

    Returns:
        Legal output files and declared licenses keyed by origin.

    Raises:
        ValueError: If an ancestry hop has no supplied publication or a legal
            file is unsafe. Missing license text is recorded as NOASSERTION.
    """
    paths: dict[tuple[str, str | None], set[str]] = {}
    for record in records:
        for chain in record.lineage:
            for hop in chain.lineage:
                paths.setdefault((hop.origin, hop.rev), set()).add(hop.path)
    sections: dict[str, list[str]] = {}
    licenses: dict[str, str] = {}
    consumer = next(
        metadata
        for (_origin, revision), (_root, metadata) in snapshots.items()
        if revision is None
    )
    owned = {
        (origin_locator(item["repo"]), item["sha"]): item
        for item in consumer.get("vendors", [])
    }
    for coordinate, shipped in sorted(
        paths.items(), key=lambda item: (item[0][0], item[0][1] or "")
    ):
        if coordinate not in snapshots:
            raise ValueError(f"Missing license publication for {coordinate[0]}")
        root, metadata = snapshots[coordinate]
        policy = (
            consumer.get("overrides", {})
            if coordinate[1] is None
            else owned.get(coordinate, {})
        )
        allow = parse_allow(policy.get("ingestAllow", []), label=coordinate[0])
        limits = (
            parse_limits(policy["ingestLimits"], label=coordinate[0])
            if "ingestLimits" in policy
            else DEFAULT_LIMITS
        )
        declared = str(metadata.get("license", "NOASSERTION"))
        licenses[coordinate[0]] = declared
        candidates: set[Path] = {root}
        for relative in shipped:
            path = root / relative
            candidates.update(
                parent for parent in path.parents if parent.is_relative_to(root)
            )
            if path.is_dir():
                candidates.add(path)
                # Nested legal texts already present in the shipped tree also
                # carry obligations; unrelated package directories do not.
                for record in records:
                    for payload in record.payload:
                        if _LEGAL.fullmatch(payload.path.name):
                            parent = path / payload.path.parent
                            if parent.is_dir():
                                candidates.add(parent)
        content: dict[str, bytes] = {}
        for directory in sorted(candidates):
            if not directory.is_dir():
                continue
            source_path(root=root, relative=directory.relative_to(root).as_posix())
            for child in iter_directory_entries(directory=directory):
                if not _LEGAL.fullmatch(child.name):
                    continue
                if child.is_symlink():
                    raise ValueError("Symlink rejected in license/notice source")
                if child.is_file():
                    data = read_bounded(path=child, vendor=coordinate[0], limits=limits)
                    inspect_bytes(
                        data=data,
                        path=child.relative_to(root).as_posix(),
                        vendor=coordinate[0],
                        allow=allow,
                    )
                    # Registry NOTICE is generated catalog metadata. Render its
                    # actual shipped subset; authored notices stay verbatim.
                    if (
                        child == root / "NOTICE.md"
                        and (root / "vendors.yaml").is_file()
                    ):
                        vendors = load_registry(registry_path=root / "vendors.yaml")
                        if data.decode("utf-8") == render_notice(vendors=vendors):
                            data = render_notice(
                                vendors=vendors,
                                origins=frozenset(origin for origin, _rev in paths),
                            ).encode()
                    content[child.relative_to(root).as_posix()] = data
        pieces = [
            section_header(
                origin=coordinate[0], revision=coordinate[1], declared=declared
            )
        ]
        pieces.extend(
            f"\n--- {path} ---\n" + data.decode("utf-8")
            for path, data in sorted(content.items())
        )
        if not content:
            pieces.append(
                "\nNo license or notice text supplied by this publication "
                "(NOASSERTION).\n"
            )
        sections.setdefault(coordinate[0], []).append("".join(pieces))
    files: Files = {
        origin_file(origin): ("\n".join(parts).encode(), 0o644)
        for origin, parts in sorted(sections.items())
    }
    notice = "# Artifact notices\n\n" + "".join(
        f"- `{origin}` — `{licenses[origin]}`; "
        f"[{origin_file(origin)}]({quote(origin_file(origin), safe='/')})\n"
        for origin in sorted(sections)
    )
    files["NOTICE.md"] = (notice.encode(), 0o644)
    return files, licenses
