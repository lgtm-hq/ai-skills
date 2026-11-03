"""Shared pytest setup for script tests.

Keeps ``scripts/`` on ``sys.path`` for repository hygiene and CI helpers only.
Engine tests import the installed ``ai_skills_engine`` package directly. Also
exposes the shared spike test helpers for the small root parity check.
"""

from __future__ import annotations

import sys
from pathlib import Path

pytest_plugins = ["provenance_helpers"]

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

SPIKE_TESTS_DIR = SCRIPTS_DIR.parent / "research" / "install-plane-spike" / "tests"

if str(SPIKE_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(SPIKE_TESTS_DIR))
