"""Outcome of reconciling one mapping path that disappeared upstream."""

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Drift:
    """A vanished mapping path with its candidates.

    Exactly one candidate reconciles the path; zero or several fail closed.

    Attributes:
        location: Manifest location of the path-bearing selector.
        selector: Declared selector value.
        old_path: Upstream path at the previous revision.
        status: ``reconciled``, ``ambiguous``, ``missing`` or ``upstream``.
        candidates: Sorted candidate paths at the new revision.
    """

    location: str
    selector: str
    old_path: str
    status: str
    candidates: tuple[str, ...] = ()

    def to_json(self) -> dict[str, object]:
        """Encode the drift outcome with stable keys.

        Returns:
            JSON-compatible mapping.
        """
        return {
            "location": self.location,
            "selector": self.selector,
            "oldPath": self.old_path,
            "status": self.status,
            "candidates": list(self.candidates),
        }
