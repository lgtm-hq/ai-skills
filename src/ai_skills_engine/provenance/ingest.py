"""Validate artifact-index chains at the pinned publication boundary."""

import json

# nosemgrep: python37-compatibility-importlib2 - requires Python >=3.13
from importlib import resources
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from ai_skills_engine.inventory.payload import source_path
from ai_skills_engine.provenance.authorship import Authorship
from ai_skills_engine.provenance.context import Context
from ai_skills_engine.provenance.hop import LineageHop
from ai_skills_engine.provenance.model import Lineage
from ai_skills_engine.registry.registry import load_unique_yaml_text

INDEX = "ai-skills.lineage.json"


def schema() -> dict[str, Any]:
    """Read the schema from the installed engine, never the caller's checkout.

    Returns:
        Packaged JSON Schema.
    """
    return dict(
        json.loads(
            resources.files(__package__)
            .joinpath("lineage.v1.schema.json")
            .read_text(encoding="utf-8")
        )
    )


def ingest(*, root: Path, context: Context) -> tuple[Lineage, ...]:
    """Ingest an optional index, authenticating every current-publication hop.

    Args:
        root: Explicit safe publisher snapshot.
        context: Expected origin and revision from the consumer's pin.

    Returns:
        Validated chains, or no declarations when there is no index.

    Raises:
        ValueError: For malformed, duplicate, cyclic or unbound declarations.
    """
    path = root / INDEX
    if not path.exists() and not path.is_symlink():
        return ()
    source_path(root=root, relative=INDEX)
    # JSON-only syntax plus duplicate-key rejection through the shared loader.
    text = path.read_text(encoding="utf-8")
    json.loads(text)
    data = load_unique_yaml_text(text=text, source=INDEX)
    envelope = {"type": "array", "items": schema()}
    errors = list(Draft202012Validator(envelope).iter_errors(data))
    if errors:
        raise ValueError("Invalid lineage index: " + errors[0].message)
    records = []
    seen: set[str] = set()
    for record in cast(list[dict[str, Any]], data):
        hops = tuple(
            LineageHop(
                origin=hop["origin"],
                publisher=hop["publisher"],
                rev=hop["rev"],
                id=hop["id"],
                path=hop["path"],
                tree_digest=hop["treeDigest"],
                renamed_from=hop.get("renamedFrom"),
                transforms=tuple(hop.get("transforms", ())),
            )
            for hop in record["lineage"]
        )
        last = hops[-1]
        if context.rev is not None and any(hop.rev is None for hop in hops):
            raise ValueError(
                f"Unpinned ancestor in imported lineage for {record['id']}"
            )
        if (last.origin, last.rev) != (
            context.origin,
            context.rev,
        ) or last.id != record["id"]:
            raise ValueError(
                f"Unbound last hop for {record['id']}: "
                f"expected {context.origin}@{context.rev}"
            )
        publications = [(hop.origin, hop.rev, hop.id) for hop in hops]
        if len(set(publications)) != len(publications):
            raise ValueError(f"Cyclic lineage for {record['id']}")
        lineage = Lineage(
            id=record["id"],
            lineage=hops,
            attestations=tuple(
                Authorship(
                    capability=item["capability"],
                    path=item["path"],
                    reason=item["reason"],
                )
                for item in record.get("attestations", ())
            ),
        )
        key = lineage.to_json()
        if key in seen:
            raise ValueError(f"Duplicate lineage for {record['id']}")
        seen.add(key)
        records.append(lineage)
    return tuple(sorted(records, key=lambda item: item.to_json()))
