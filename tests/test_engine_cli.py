"""Test installed CLI routing, discovery and real package monkeypatch identity."""

from __future__ import annotations

from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli, package_sync
from ai_skills_engine.bake import vendor_indexes
from ai_skills_engine.paths import find_repo_root
from ai_skills_engine.vendors import manage


def test_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Top-level help lists all author commands without needing a repository."""
    with pytest.raises(SystemExit) as error:
        cli.main(["--help"])
    assert_that(error.value.code).is_zero()
    assert_that(capsys.readouterr().out).contains(
        "validate-skills",
        "generate",
        "bake",
        "vendors",
        "repin",
        "package-sync",
    )


def test_find_repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Discovery walks cwd ancestors and requires both repository markers."""
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "skills").mkdir()
    nested = tmp_path / "nested" / "directory"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert_that(find_repo_root()).is_equal_to(tmp_path)
    assert_that(find_repo_root(nested)).is_equal_to(tmp_path)


def test_discovery_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Outside-repository failures identify the explicit-root recovery flag."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="--repo-root"):
        find_repo_root()
    with pytest.raises(SystemExit) as error:
        cli.main(["repin", "--list-json"])
    assert_that(error.value.code).is_equal_to(2)
    assert_that(capsys.readouterr().err).contains(
        "No ai-skills repository", "--repo-root"
    )


def test_package_module_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CLI dispatch and collaborating modules see the actual patched modules."""
    roots: list[Path] = []
    monkeypatch.setattr(
        vendor_indexes, "check", lambda *, repo_root: roots.append(repo_root) or 7
    )
    assert_that(
        cli.main(["--repo-root", str(tmp_path), "bake", "vendor-indexes", "--check"])
    ).is_equal_to(7)
    assert_that(roots).is_equal_to([tmp_path])
    assert_that(manage.bake_vendor_indexes).is_same_as(vendor_indexes)
    assert_that(manage.package_sync).is_same_as(package_sync)


def test_sync_explicit_roots_do_not_leak(tmp_path: Path) -> None:
    """Selecting one repository never mutates the next operation's roots."""
    first, second = tmp_path / "first", tmp_path / "second"
    assert_that(package_sync.baked_plugin_dest(repo_root=first)).is_equal_to(
        first / "npm" / "ai-skills" / "data" / "plugins-baked",
    )
    assert_that(package_sync.baked_plugin_dest(repo_root=second)).is_equal_to(
        second / "npm" / "ai-skills" / "data" / "plugins-baked",
    )
