"""Tests for ``scripts/generate_marketplace.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from assertpy import assert_that


def _load_generate_marketplace_module() -> ModuleType:
    """Load ``generate_marketplace`` from the scripts directory (not a package).

    Returns:
        The loaded module object.

    Raises:
        RuntimeError: If the module spec or loader cannot be constructed.
    """
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "generate_marketplace.py"
    spec = importlib.util.spec_from_file_location(
        name="generate_marketplace",
        location=path,
    )
    if spec is None:
        msg = f"Could not load module spec from {path}"
        raise RuntimeError(msg)
    loader = spec.loader
    if loader is None:
        msg = f"Module spec for {path} has no loader"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def _write_skill(*, repo_root: Path, skill_id: str) -> None:
    """Create a minimal skill directory for tests.

    Args:
        repo_root: Fake repository root.
        skill_id: Skill directory name under ``skills/``.
    """
    skill_dir = repo_root / "skills" / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(
        f"---\nname: {skill_id}\ndescription: Test skill.\n---\n",
        encoding="utf-8",
    )


def _write_bundles(*, repo_root: Path, body: str) -> None:
    """Write ``bundles.yaml`` in a fake repository root.

    Args:
        repo_root: Fake repository root.
        body: YAML file contents.
    """
    repo_root.joinpath("bundles.yaml").write_text(body, encoding="utf-8")


def test_generate_marketplace_builds_plugin_groups(tmp_path: Path) -> None:
    """Grouped skills become named plugins with ./skills/<id> paths."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_skill(repo_root=tmp_path, skill_id="beta")
    _write_bundles(
        repo_root=tmp_path,
        body="""
groups:
  core:
    name: Core Workflow
    skills:
      - alpha
ungrouped:
  - beta
""",
    )

    rendered = mod.generate_marketplace(repo_root=tmp_path)
    manifest = json.loads(rendered)

    assert_that(manifest).is_equal_to(
        {
            "plugins": [
                {
                    "name": "Core Workflow",
                    "source": "./",
                    "skills": ["./skills/alpha"],
                },
            ],
        }
    )


def test_validate_bundles_rejects_missing_skill(tmp_path: Path) -> None:
    """Every skill directory must appear in bundles.yaml."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="only-one")
    _write_bundles(
        repo_root=tmp_path,
        body="""
groups:
  core:
    name: Core
    skills: []
ungrouped: []
""",
    )

    with pytest.raises(ValueError, match="missing skills: only-one"):
        mod.generate_marketplace(repo_root=tmp_path)


def test_validate_bundles_rejects_duplicate_assignment(tmp_path: Path) -> None:
    """A skill cannot appear in two groups."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="dup")
    _write_bundles(
        repo_root=tmp_path,
        body="""
groups:
  one:
    name: One
    skills:
      - dup
  two:
    name: Two
    skills:
      - dup
ungrouped: []
""",
    )

    with pytest.raises(ValueError, match="listed in both"):
        mod.generate_marketplace(repo_root=tmp_path)


def test_repo_bundles_cover_all_skills() -> None:
    """Production bundles.yaml must account for every skill in skills/."""

    mod = _load_generate_marketplace_module()
    repo_root = Path(__file__).resolve().parents[1]

    # Should not raise.
    mod.generate_marketplace(repo_root=repo_root)
