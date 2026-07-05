"""The ``DriftResult`` record for one skill's drift comparison."""

from __future__ import annotations

from dataclasses import dataclass

from upstream_drift.tracked_skill import TrackedSkill


@dataclass(frozen=True)
class DriftResult:
    """Outcome of comparing one tracked skill against upstream.

    Attributes:
        skill: The tracked skill that was compared.
        drifted: Whether the normalized bodies differ.
        diff: Unified diff of the normalized bodies (empty when equal).
    """

    skill: TrackedSkill
    drifted: bool
    diff: str
