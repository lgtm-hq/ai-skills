"""Tests for the generated ai-skills npm package contents."""

from __future__ import annotations

from pathlib import Path

import pytest
from assertpy import assert_that

import ai_skills_engine.package_sync as module

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_generated_package_is_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the committed npm data catalog synchronized with its root sources.

    A local ``plugins-baked/`` leftover must not fail this first-party check;
    bake output is a publish-time artifact (ADR-0007).
    """
    monkeypatch.setattr(
        module, "baked_plugin_source", lambda **kwargs: tmp_path / "absent"
    )

    assert_that(module.check_rendered(module.rendered_files("0.0.0-dev"))).is_zero()


def test_check_skips_baked_plugins_when_source_absent(
    tmp_path: Path,
) -> None:
    """First-party --check does not require a local plugins-baked tree."""
    files = {tmp_path / "keep.txt": "ok\n"}
    (tmp_path / "keep.txt").write_text("ok\n", encoding="utf-8")

    assert_that(module.check_rendered(files=files, repo_root=tmp_path)).is_zero()


def test_write_copies_baked_plugins_into_package(
    tmp_path: Path,
) -> None:
    """Sync copies plugins-baked into npm data when a local bake exists."""
    source = tmp_path / "plugins-baked"
    dest_root = tmp_path / "npm" / "ai-skills" / "data"
    source.mkdir()
    (source / "COVERAGE.md").write_text("coverage\n", encoding="utf-8")

    module.write_baked_plugins(repo_root=tmp_path)

    copied = dest_root / "plugins-baked" / "COVERAGE.md"
    assert_that(copied.read_text(encoding="utf-8")).is_equal_to("coverage\n")
    assert_that(module.check_baked_plugins(repo_root=tmp_path)).is_false()


def test_check_detects_stale_baked_plugin_copy(
    tmp_path: Path,
) -> None:
    """Sync --check fails when the package copy diverges from the bake."""
    source = tmp_path / "plugins-baked"
    dest = tmp_path / "npm" / "ai-skills" / "data" / "plugins-baked"
    source.mkdir()
    dest.mkdir(parents=True)
    (source / "COVERAGE.md").write_text("fresh\n", encoding="utf-8")
    (dest / "COVERAGE.md").write_text("stale\n", encoding="utf-8")

    assert_that(module.check_baked_plugins(repo_root=tmp_path)).is_true()


def test_write_removes_baked_copy_when_source_absent(
    tmp_path: Path,
) -> None:
    """A leftover package copy is deleted when plugins-baked is missing."""
    dest = tmp_path / "npm" / "ai-skills" / "data" / "plugins-baked"
    dest.mkdir(parents=True)
    (dest / "COVERAGE.md").write_text("leftover\n", encoding="utf-8")

    module.write_baked_plugins(repo_root=tmp_path)

    assert_that(dest.exists()).is_false()


def test_normalize_version_removes_tag_prefix() -> None:
    """Translate release tags into valid npm semver versions."""

    assert_that(module.normalize_version("v1.2.3")).is_equal_to("1.2.3")


def test_normalize_version_rejects_invalid_release_tag() -> None:
    """Reject release tags that cannot become npm semver versions."""

    with pytest.raises(ValueError, match="Invalid npm semver version"):
        module.normalize_version("ai-skills-v1.2.3")
