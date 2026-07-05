"""Upstream drift detection for skills sourced from other repositories.

Focused modules behind the ``scripts/check_upstream_drift.py`` CLI:

- ``tracked_skill``: the ``TrackedSkill`` record,
- ``drift_result``: the ``DriftResult`` record,
- ``discovery``: finding skills with an ``upstream`` frontmatter block,
- ``fetch``: fetching upstream files (with URL-safety guards),
- ``compare``: body normalization and drift comparison,
- ``issues``: tracking-issue rendering and filing via ``gh``.
"""

from __future__ import annotations

from upstream_drift.compare import check_skill_drift, normalize_body
from upstream_drift.discovery import find_tracked_skills
from upstream_drift.drift_result import DriftResult
from upstream_drift.fetch import fetch_upstream_text
from upstream_drift.issues import file_tracking_issue
from upstream_drift.tracked_skill import TrackedSkill

__all__ = [
    "DriftResult",
    "TrackedSkill",
    "check_skill_drift",
    "fetch_upstream_text",
    "file_tracking_issue",
    "find_tracked_skills",
    "normalize_body",
]
