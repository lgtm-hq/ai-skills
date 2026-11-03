"""Actionable selection findings."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SelectionDiagnostic:
    """Finding with a shortest root chain and an explicit repair suggestion."""

    code: str
    location: str
    message: str
    chain: tuple[str, ...]
    fix: str
    warning: bool = False
    cycle: tuple[str, ...] = ()
