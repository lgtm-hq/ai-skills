"""Validated role-qualified capability identity."""

from dataclasses import dataclass
from typing import Self

from ai_skills_engine.inventory.package_id import PackageId
from ai_skills_engine.manifest.identity import Role, parse_id


@dataclass(frozen=True, order=True)
class CapabilityId:
    """Stable package, role and declared name, never a content hash."""

    package: PackageId
    role: Role
    name: str

    def __post_init__(self) -> None:
        """Validate direct construction as well as parsed input."""
        _, _, role, name = parse_id(str(self))
        if role != self.role or name != self.name:
            raise ValueError(f"Invalid capability ID: {self}")

    @classmethod
    def parse(cls, value: str) -> Self:
        """Parse an exact capability identity.

        Args:
            value: Qualified identity.

        Returns:
            Validated ID.

        Raises:
            ValueError: On a malformed or non-capability identity.
        """
        publisher, package, role, name = parse_id(value)
        return cls(
            package=PackageId(publisher=publisher, name=package),
            role=Role(role),
            name=name,
        )

    def __str__(self) -> str:
        """Render the qualified identity.

        Returns:
            Package-qualified role/name.
        """
        return f"{self.package}:{self.role}/{self.name}"
