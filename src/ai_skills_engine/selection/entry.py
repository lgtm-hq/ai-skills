"""Explain record for one qualified identity."""

from dataclasses import dataclass

from ai_skills_engine.selection.state import State


@dataclass(frozen=True)
class SelectionEntry:
    """Disposition, reason, destination names and shortest root path."""

    id: str
    state: State
    reason: str
    chain: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
