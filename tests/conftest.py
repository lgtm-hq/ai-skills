"""Shared pytest setup for script tests.

Puts ``scripts/`` on ``sys.path`` so tests can import script helpers
the same way the CLI entrypoints do (``python scripts/<name>.py``
places ``scripts/`` at ``sys.path[0]``). Also exposes the shared spike test
helpers so the small root parity check can reuse the isolated harness fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

SPIKE_TESTS_DIR = SCRIPTS_DIR.parent / "research" / "install-plane-spike" / "tests"

if str(SPIKE_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(SPIKE_TESTS_DIR))
