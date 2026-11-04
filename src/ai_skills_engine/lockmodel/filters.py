"""Vendor import filters recorded by the resolution lock."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Filters:
    """Manifest ``include``/``exclude`` selectors of one vendor import.

    Attributes:
        include: Declared include selectors, in manifest order.
        exclude: Declared exclude selectors, in manifest order.
    """

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        """Encode the record with its lock field names.

        Returns:
            JSON-compatible mapping.
        """
        return {"include": list(self.include), "exclude": list(self.exclude)}
