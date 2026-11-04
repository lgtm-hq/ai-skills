"""One built standalone resource recorded by the resolution lock."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LockedResource:
    """Resource identity and authoritative lineage copied from the artifact index.

    Attributes:
        id: Qualified resource ID.
        lineage: Index lineage chains, verbatim.
    """

    id: str
    lineage: tuple[dict[str, Any], ...]

    def to_json(self) -> dict[str, Any]:
        """Encode the record with its lock field names.

        Returns:
            JSON-compatible mapping.
        """
        return {"id": self.id, "lineage": list(self.lineage)}
