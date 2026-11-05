"""Shared pytest setup for script tests.

Keeps ``scripts/`` on ``sys.path`` for repository hygiene and CI helpers only.
Engine tests import the installed ``ai_skills_engine`` package directly. Also
exposes the shared spike test helpers for the small root parity check.
Plugins must defer engine imports until use so that isolated spike discovery
does not require the root project's runtime installation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest_plugins = ["provenance_helpers"]
pytest.register_assert_rewrite("artifact_helpers")

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

SPIKE_TESTS_DIR = SCRIPTS_DIR.parent / "research" / "install-plane-spike" / "tests"

if str(SPIKE_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(SPIKE_TESTS_DIR))


@pytest.fixture(autouse=True)
def isolated_source_cache(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Keep every test's source cache private, never the user's cache.

    Args:
        tmp_path_factory: Session temporary directory factory.
        monkeypatch: Environment patcher; child processes inherit the value.

    Returns:
        Private ``AI_SKILLS_CACHE`` root for this test.
    """
    root = tmp_path_factory.mktemp("source-cache")
    monkeypatch.setenv("AI_SKILLS_CACHE", str(root))
    return root
