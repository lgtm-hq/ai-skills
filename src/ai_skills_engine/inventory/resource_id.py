"""Validated resource identity."""

from dataclasses import dataclass
from typing import Self

from ai_skills_engine.inventory.package_id import PackageId
from ai_skills_engine.manifest.identity import parse_id


@dataclass(frozen=True, order=True)
class ResourceId:
    """Package-qualified resource name."""

    package: PackageId
    name: str

    def __post_init__(self) -> None:
        """Validate direct construction."""
        _, _, role, name = parse_id(str(self))
        if role != "resource" or name != self.name:
            raise ValueError(f"Invalid resource ID: {self}")

    @classmethod
    def parse(cls, value: str) -> Self:
        """Parse an exact resource identity.

        Args:
            value: Qualified identity.

        Returns:
            Validated resource ID.

        Raises:
            ValueError: On a malformed or non-resource identity.
        """
        publisher, package, role, name = parse_id(value)
        if role != "resource":
            raise ValueError(f"Expected resource ID: {value}")
        return cls(package=PackageId(publisher=publisher, name=package), name=name)

    def __str__(self) -> str:
        """Render the qualified identity.

        Returns:
            Package-qualified resource name.
        """
        return f"{self.package}:resource/{self.name}"
