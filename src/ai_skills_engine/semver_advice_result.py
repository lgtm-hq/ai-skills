"""Non-binding release advice from a resolved artifact diff."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SemverAdvice:
    """Highest recommended level and deterministic human-readable reasons."""

    level: Literal["major", "minor", "patch", "none"]
    reasons: tuple[str, ...]
