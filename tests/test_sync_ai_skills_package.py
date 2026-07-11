"""Tests for the generated ai-skills npm package contents."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from assertpy import assert_that

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "ci" / "npm" / "sync_ai_skills_package.py"


def load_sync_module() -> ModuleType:
    """Load the npm package synchronization script as a module.

    Returns:
        Loaded synchronization module.
    """
    specification = importlib.util.spec_from_file_location(
        "sync_ai_skills_package",
        SCRIPT_PATH,
    )
    if specification is None or specification.loader is None:
        msg = f"Could not load {SCRIPT_PATH}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_generated_package_is_current() -> None:
    """Keep the committed npm data catalog synchronized with its root sources."""
    module = load_sync_module()

    assert_that(module.check_rendered(module.rendered_files("0.0.0-dev"))).is_zero()


def test_normalize_version_removes_tag_prefix() -> None:
    """Translate release tags into valid npm semver versions."""
    module = load_sync_module()

    assert_that(module.normalize_version("v1.2.3")).is_equal_to("1.2.3")


def test_normalize_version_rejects_invalid_release_tag() -> None:
    """Reject release tags that cannot become npm semver versions."""
    module = load_sync_module()

    with pytest.raises(ValueError, match="Invalid npm semver version"):
        module.normalize_version("ai-skills-v1.2.3")
