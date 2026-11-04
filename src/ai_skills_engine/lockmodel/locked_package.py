"""One built package artifact recorded by the resolution lock."""

from dataclasses import dataclass
from typing import Any

from ai_skills_engine.lockmodel.locked_capability import LockedCapability
from ai_skills_engine.lockmodel.locked_resource import LockedResource


@dataclass(frozen=True)
class LockedPackage:
    """Package tar identity, tree identity and contents.

    Attributes:
        id: Qualified package ID.
        version: Package version from the artifact index.
        artifact_digest: SHA-256 of the uncompressed package tar.
        tree_digest: Digest of the package payload tree.
        capabilities: Capabilities the package owns.
        resources: Standalone resources the package owns, including
            artifact-only resources declared in the index ``resources[]``.
    """

    id: str
    version: str
    artifact_digest: str
    tree_digest: str
    capabilities: tuple[LockedCapability, ...]
    resources: tuple[LockedResource, ...]

    def to_json(self) -> dict[str, Any]:
        """Encode the record with its lock field names.

        Returns:
            JSON-compatible mapping.
        """
        return {
            "id": self.id,
            "version": self.version,
            "artifactDigest": self.artifact_digest,
            "treeDigest": self.tree_digest,
            "capabilities": [item.to_json() for item in self.capabilities],
            "resources": [item.to_json() for item in self.resources],
        }
