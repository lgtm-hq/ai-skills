"""Shared pytest setup for script tests.

Puts ``scripts/`` on ``sys.path`` so tests can import the
``upstream_drift`` package and the ``skill_frontmatter`` helper the
same way the CLI entrypoints do (``python scripts/<name>.py`` places
``scripts/`` at ``sys.path[0]``).
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
