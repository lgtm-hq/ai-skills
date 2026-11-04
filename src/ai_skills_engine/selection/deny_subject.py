"""Lineage-ready input bound to the inventory's resource identities."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DenySubject:
    """Observed origin, declared ancestor origins and required resource subjects."""

    id: str
    origin: str
    lineage: tuple[str, ...] = ()
    resources: tuple["DenySubject", ...] = ()
