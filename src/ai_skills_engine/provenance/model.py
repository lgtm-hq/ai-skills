"""Deterministic lineage chains; multiple chains retain deduplicated ancestry."""

import json
from dataclasses import asdict, dataclass
from typing import Any

from ai_skills_engine.manifest.codec import field_key
from ai_skills_engine.provenance.authorship import Authorship
from ai_skills_engine.provenance.hop import LineageHop


def json_value(value: Any) -> Any:
    """Convert nested dataclass dictionaries to the published camelCase contract.

    Args:
        value: Plain dataclass values.

    Returns:
        JSON-compatible values with canonical field names.
    """
    if isinstance(value, dict):
        return {field_key(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class Lineage:
    """A single ordered chain and descriptive, non-authoritative attestations."""

    id: str
    lineage: tuple[LineageHop, ...]
    attestations: tuple[Authorship, ...] = ()

    def to_json(self) -> str:
        """Serialize a chain against the packaged v1 schema.

        Returns:
            Stable JSON, independent of checkout paths and mapping order.
        """
        return json.dumps(json_value(asdict(self)), indent=2, sort_keys=True) + "\n"


def union_lineage(*groups: tuple[Lineage, ...]) -> tuple[Lineage, ...]:
    """Retain all distinct chains when already-authorized copies are deduplicated.

    Args:
        groups: Lineages of copies after consumer denies have been evaluated.

    Returns:
        Stable union, preserving every ancestor and attestation.
    """
    return tuple(
        sorted(
            {item for group in groups for item in group},
            key=lambda item: item.to_json(),
        )
    )
