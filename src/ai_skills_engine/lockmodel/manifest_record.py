"""Manifest identity recorded by the resolution lock."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ManifestRecord:
    """Digests of the parsed manifest and of the local author inputs.

    Attributes:
        api_version: Manifest ``apiVersion``.
        digest: Digest of the canonical parsed ``ai-skills.yaml`` (key order and
            formatting do not matter).
        inputs_digest: Digest of local payloads, legal files and builder sources
            that the offline drift gate checks without vendor sources.
    """

    api_version: str
    digest: str
    inputs_digest: str

    def to_json(self) -> dict[str, Any]:
        """Encode the record with its lock field names.

        Returns:
            JSON-compatible mapping.
        """
        return {
            "apiVersion": self.api_version,
            "digest": self.digest,
            "inputsDigest": self.inputs_digest,
        }
