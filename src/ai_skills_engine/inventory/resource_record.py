"""Declared resource bytes retaining their source identity."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from ai_skills_engine.inventory.payload_file import PayloadFile
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.provenance.model import Lineage


@dataclass(frozen=True)
class Resource:
    """A declared shared file or directory and its deterministic payload."""

    id: ResourceId
    origin: str
    source_path: PurePosixPath
    payload: tuple[PayloadFile, ...]
    tree_digest: str
    lineage: tuple[Lineage, ...] = ()
