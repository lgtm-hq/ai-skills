"""Selector analysis of one vendor declaration at a new revision."""

from dataclasses import dataclass, field
from typing import Any

from ai_skills_engine.repin.change import Change
from ai_skills_engine.repin.drift import Drift
from ai_skills_engine.repin.selector_status import SelectorStatus


@dataclass(frozen=True)
class SelectorPlan:
    """Rewritten declaration plus every selector outcome and failure.

    Attributes:
        entry: Vendor declaration after reconciled paths and declared renames.
        statuses: Selector match counts.
        drifts: Path-drift outcomes.
        moves: Identical content found at a different name (never applied).
        failures: Actionable failures; non-empty fails the re-pin.
    """

    entry: dict[str, Any]
    statuses: tuple[SelectorStatus, ...] = ()
    drifts: tuple[Drift, ...] = ()
    moves: tuple[Change, ...] = ()
    failures: tuple[str, ...] = field(default_factory=tuple)
