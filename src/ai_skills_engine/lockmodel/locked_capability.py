"""One built capability recorded by the resolution lock."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LockedCapability:
    """Capability closure and authoritative lineage copied from the artifact index.

    Attributes:
        id: Qualified capability ID.
        closure: Sorted capability and resource IDs of its hard closure.
        lineage: Index lineage chains, verbatim.
    """

    id: str
    closure: tuple[str, ...]
    lineage: tuple[dict[str, Any], ...]

    def to_json(self) -> dict[str, Any]:
        """Encode the record with its lock field names.

        Returns:
            JSON-compatible mapping.
        """
        return {
            "id": self.id,
            "closure": list(self.closure),
            "lineage": list(self.lineage),
        }
