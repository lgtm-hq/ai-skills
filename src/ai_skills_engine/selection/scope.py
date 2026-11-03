"""Consumer-owned selection boundary."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SelectionScope:
    """Qualified inventory members governed by one package or vendor declaration."""

    location: str
    members: tuple[str, ...]
    include: tuple[str, ...] | None = None
    exclude: tuple[str, ...] | None = None
