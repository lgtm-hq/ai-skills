"""Match count and outcome of one consumer selector at the new revision."""

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class SelectorStatus:
    """A consumer-owned selector and how many upstream items it matches.

    Attributes:
        location: Manifest location, for example ``mapping.packages[x].skills``.
        selector: Declared selector value after any applied rewrite.
        matches: Items matched at the new revision.
        status: ``ok``, ``dead``, ``reconciled`` or ``renamed``.
        detail: Rewrite description, empty when the selector is unchanged.
    """

    location: str
    selector: str
    matches: int
    status: str
    detail: str = ""

    def to_json(self) -> dict[str, str | int]:
        """Encode the selector with stable keys.

        Returns:
            JSON-compatible mapping.
        """
        return {
            "location": self.location,
            "selector": self.selector,
            "matches": self.matches,
            "status": self.status,
            "detail": self.detail,
        }
