"""Explicit build-plane pinned acquisition, separate from offline artifact writing."""

from collections.abc import Mapping
from pathlib import Path

from ai_skills_engine.bake.vendor_plugins import _fetch_vendor_tree
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.registry.ingest_checks import parse_limits
from ai_skills_engine.registry.ingest_limits import IngestLimits
from ai_skills_engine.registry.vendor import Vendor


def acquire_inputs(
    *, root: Path, supplied: Mapping[str, Path], temporary: Path
) -> dict[str, Path]:
    """Fetch only explicitly authorized missing pins, retaining pristine input bytes.

    Args:
        root: Consumer manifest root.
        supplied: Caller-provided slash-qualified pinned snapshots.
        temporary: Private build-lifetime acquisition directory.

    Returns:
        Complete available source map, including nested declared pins.

    Raises:
        ValueError: For recursive imports or an excessive nesting depth.
    """
    roots = dict(supplied)
    pending: list[tuple[Path, str, tuple[tuple[str, str], ...]]] = [(root, "", ())]
    while pending:
        current, prefix, ancestors = pending.pop()
        for entry in read_document(current / "ai-skills.yaml").get("vendors", []):
            identity = (entry["repo"], entry["sha"])
            if identity in ancestors or len(ancestors) >= 64:
                raise ValueError("Recursive pinned artifact input")
            alias = prefix + entry["id"]
            if alias not in roots:
                vendor = Vendor(
                    id=entry["id"],
                    repo=entry["repo"],
                    sha=entry["sha"],
                    skill_roots=(),
                    license=entry.get("license", ""),
                    homepage=entry.get("homepage", ""),
                    ingest_limits=(
                        parse_limits(entry["ingestLimits"], label=alias)
                        if "ingestLimits" in entry
                        else IngestLimits()
                    ),
                )
                destination = temporary / str(len(roots))
                _fetch_vendor_tree(vendor=vendor, dest=destination)
                roots[alias] = destination
            if (roots[alias] / "ai-skills.yaml").is_file():
                pending.append((roots[alias], alias + "/", (*ancestors, identity)))
    return roots
