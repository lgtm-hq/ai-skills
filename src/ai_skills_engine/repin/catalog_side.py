"""One built catalog observed for a re-pin comparison."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CatalogSide:
    """Index, payload file digests and tar digests of one complete build.

    Attributes:
        index: Catalog ``index.json`` of the build.
        files: Artifact member path to ``sha256:<hex>:<mode>``.
        artifact_digests: Package ID to the tar ``artifactDigest``.
        diagnostics: Selection errors observed while building, if any.
    """

    index: Mapping[str, Any]
    files: Mapping[str, str] = field(default_factory=dict)
    artifact_digests: Mapping[str, str] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
