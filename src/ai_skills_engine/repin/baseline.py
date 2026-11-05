"""Manifest and lock bytes the re-pin summary compares against."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Baseline:
    """Base-branch declarations, so branch-only edits never skew the diff.

    Attributes:
        manifest_text: ``ai-skills.yaml`` at the baseline.
        lock_bytes: ``ai-skills.lock`` at the baseline, None when absent.
    """

    manifest_text: str
    lock_bytes: bytes | None = None
