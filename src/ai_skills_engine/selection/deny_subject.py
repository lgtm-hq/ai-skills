"""Lineage-ready input bound to the inventory's resource identities."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DenySubject:
    """Immediate origin today; authenticated ancestor origins may be added later."""

    id: str
    origin: str
    lineage: tuple[str, ...] = ()
    resources: tuple["DenySubject", ...] = ()
