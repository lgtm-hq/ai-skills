"""Validated package identity independent of transport or payload bytes."""

from dataclasses import dataclass
from typing import Self

from ai_skills_engine.manifest.identity import parse_id


@dataclass(frozen=True, order=True)
class PackageId:
    """Publisher-qualified package identity."""

    publisher: str
    name: str

    def __post_init__(self) -> None:
        """Reject malformed components at construction."""
        publisher, package, role, _ = parse_id(str(self))
        if role or (publisher, package) != (self.publisher, self.name):
            raise ValueError(f"Invalid package ID: {self}")

    @classmethod
    def parse(cls, value: str) -> Self:
        """Parse an exact package ID.

        Args:
            value: Qualified identity.

        Returns:
            Validated ID.

        Raises:
            ValueError: On a malformed or non-package identity.
        """
        publisher, package, role, _ = parse_id(value)
        if role:
            raise ValueError(f"Expected package ID: {value}")
        return cls(publisher=publisher, name=package)

    def __str__(self) -> str:
        """Render the stable qualified identity.

        Returns:
            Qualified package name.
        """
        return f"{self.publisher}/{self.name}"
