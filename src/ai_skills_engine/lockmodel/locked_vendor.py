"""One resolved vendor source recorded by the resolution lock."""

from dataclasses import dataclass
from typing import Any

from ai_skills_engine.lockmodel.filters import Filters


@dataclass(frozen=True)
class LockedVendor:
    """A pinned vendor import and the digest of its canonical source tree.

    Attributes:
        id: Vendor alias; nested imports use slash-qualified aliases.
        repo: ``owner/name`` repository.
        sha: Pinned 40-hex commit.
        source_digest: Digest of the canonical extracted tree.
        filters: Declared import filters.
    """

    id: str
    repo: str
    sha: str
    source_digest: str
    filters: Filters

    def to_json(self) -> dict[str, Any]:
        """Encode the record with its lock field names.

        Returns:
            JSON-compatible mapping.
        """
        return {
            "id": self.id,
            "repo": self.repo,
            "sha": self.sha,
            "sourceDigest": self.source_digest,
            "filters": self.filters.to_json(),
        }
