"""One sorted line of a re-pin report."""

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Change:
    """A subject, what happened to it and an optional detail.

    Attributes:
        subject: Qualified ID, package, path or selector the line describes.
        kind: Stable change verb such as ``added``, ``removed`` or ``~``.
        detail: Additional deterministic context, empty when not applicable.
    """

    subject: str
    kind: str
    detail: str = ""

    def to_json(self) -> dict[str, str]:
        """Encode the line with stable keys.

        Returns:
            JSON-compatible mapping.
        """
        return {"subject": self.subject, "kind": self.kind, "detail": self.detail}
