"""Builder identity recorded by the resolution lock."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Builder:
    """Engine distribution and artifact format that produced the lock.

    Attributes:
        engine_version: Installed ``ai-skills`` distribution version.
        artifact_format: Artifact index format version.
    """

    engine_version: str
    artifact_format: int

    def to_json(self) -> dict[str, Any]:
        """Encode the record with its lock field names.

        Returns:
            JSON-compatible mapping.
        """
        return {
            "engineVersion": self.engine_version,
            "artifactFormat": self.artifact_format,
        }
