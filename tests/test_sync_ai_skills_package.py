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


def test_generated_package_is_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the committed npm data catalog synchronized with its root sources.

    A local ``plugins-baked/`` leftover must not fail this first-party check;
    bake output is a publish-time artifact (ADR-0007).
    """
    module = load_sync_module()
    monkeypatch.setattr(module, "baked_plugin_source", lambda: tmp_path / "absent")

    assert_that(module.check_rendered(module.rendered_files("0.0.0-dev"))).is_zero()


def test_check_skips_baked_plugins_when_source_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First-party --check does not require a local plugins-baked tree."""
    module = load_sync_module()
    files = {tmp_path / "keep.txt": "ok\n"}
    (tmp_path / "keep.txt").write_text("ok\n", encoding="utf-8")
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "DATA_ROOT", tmp_path / "data")

    assert_that(module.check_rendered(files=files)).is_zero()


def test_write_copies_baked_plugins_into_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sync copies plugins-baked into npm data when a local bake exists."""
    module = load_sync_module()
    source = tmp_path / "plugins-baked"
    dest_root = tmp_path / "npm-data"
    source.mkdir()
    (source / "COVERAGE.md").write_text("coverage\n", encoding="utf-8")
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "DATA_ROOT", dest_root)

    module.write_baked_plugins()

    copied = dest_root / "plugins-baked" / "COVERAGE.md"
    assert_that(copied.read_text(encoding="utf-8")).is_equal_to("coverage\n")
    assert_that(module.check_baked_plugins()).is_false()


def test_check_detects_stale_baked_plugin_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sync --check fails when the package copy diverges from the bake."""
    module = load_sync_module()
    source = tmp_path / "plugins-baked"
    dest = tmp_path / "data" / "plugins-baked"
    source.mkdir()
    dest.mkdir(parents=True)
    (source / "COVERAGE.md").write_text("fresh\n", encoding="utf-8")
    (dest / "COVERAGE.md").write_text("stale\n", encoding="utf-8")
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "DATA_ROOT", tmp_path / "data")

    assert_that(module.check_baked_plugins()).is_true()


def test_write_removes_baked_copy_when_source_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A leftover package copy is deleted when plugins-baked is missing."""
    module = load_sync_module()
    dest = tmp_path / "data" / "plugins-baked"
    dest.mkdir(parents=True)
    (dest / "COVERAGE.md").write_text("leftover\n", encoding="utf-8")
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "DATA_ROOT", tmp_path / "data")

    module.write_baked_plugins()

    assert_that(dest.exists()).is_false()


def test_normalize_version_removes_tag_prefix() -> None:
    """Translate release tags into valid npm semver versions."""
    module = load_sync_module()

    assert_that(module.normalize_version("v1.2.3")).is_equal_to("1.2.3")


def test_normalize_version_rejects_invalid_release_tag() -> None:
    """Reject release tags that cannot become npm semver versions."""
    module = load_sync_module()

    with pytest.raises(ValueError, match="Invalid npm semver version"):
        module.normalize_version("ai-skills-v1.2.3")
