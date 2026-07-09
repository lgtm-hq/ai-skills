"""Tests for ``scripts/generate_readme.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from assertpy import assert_that


def _load_generate_readme_module() -> ModuleType:
    """Load ``generate_readme`` from the scripts directory (not a package).

    Returns:
        The loaded module object.

    Raises:
        RuntimeError: If the module spec or loader cannot be constructed.
    """
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "generate_readme.py"
    spec = importlib.util.spec_from_file_location(
        name="generate_readme",
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


def _write_skill(*, repo_root: Path, skill_id: str, description: str) -> None:
    """Create a minimal skill directory for tests.

    Args:
        repo_root: Fake repository root.
        skill_id: Skill directory name under ``skills/``.
        description: Frontmatter description value.
    """
    skill_dir = repo_root / "skills" / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(
        f"---\nname: {skill_id}\ndescription: {description}\n---\n",
        encoding="utf-8",
    )


def _write_fake_repo(*, repo_root: Path) -> None:
    """Populate a fake repository with skills, bundles, pyproject, README.

    Args:
        repo_root: Fake repository root.
    """
    _write_skill(
        repo_root=repo_root,
        skill_id="alpha",
        description="Do alpha things. Use when asked for alpha.",
    )
    _write_skill(
        repo_root=repo_root,
        skill_id="beta",
        description="Do beta things.",
    )
    repo_root.joinpath("bundles.yaml").write_text(
        """
groups:
  core:
    name: Core Workflow
    description: Everyday workflow skills.
    skills:
      - alpha
ungrouped:
  - beta
""",
        encoding="utf-8",
    )
    repo_root.joinpath("pyproject.toml").write_text(
        '[project]\nname = "fake"\nversion = "9.9.9"\n',
        encoding="utf-8",
    )
    repo_root.joinpath("README.md").write_text(
        "# fake\n\n"
        "```bash\nbunx skills add lgtm-hq/ai-skills@v0.0.1 -g\n"
        "gh release download v0.0.1 -R lgtm-hq/ai-skills\n```\n\n"
        "## Skills\n\n"
        "<!-- skills:start -->\nstale\n<!-- skills:end -->\n\n"
        "## License\n",
        encoding="utf-8",
    )


def test_render_readme_builds_hyperlinked_groups(tmp_path: Path) -> None:
    """Groups render as headings with skills linked to their SKILL.md."""

    mod = _load_generate_readme_module()
    _write_fake_repo(repo_root=tmp_path)

    rendered = mod.render_readme(repo_root=tmp_path)

    assert_that(rendered).contains("### Core Workflow")
    assert_that(rendered).contains("Everyday workflow skills.")
    assert_that(rendered).contains(
        "- **[alpha](skills/alpha/SKILL.md)** — Do alpha things.",
    )
    assert_that(rendered).does_not_contain("Use when asked for alpha.")
    assert_that(rendered).does_not_contain("stale")


def test_render_readme_puts_ungrouped_skills_under_other(tmp_path: Path) -> None:
    """Ungrouped skills appear under the Other heading, hyperlinked."""

    mod = _load_generate_readme_module()
    _write_fake_repo(repo_root=tmp_path)

    rendered = mod.render_readme(repo_root=tmp_path)

    assert_that(rendered).contains("### Other")
    assert_that(rendered).contains(
        "- **[beta](skills/beta/SKILL.md)** — Do beta things.",
    )


def test_render_readme_syncs_version_pins_to_pyproject(tmp_path: Path) -> None:
    """Release-tag pins are rewritten to the pyproject.toml version."""

    mod = _load_generate_readme_module()
    _write_fake_repo(repo_root=tmp_path)

    rendered = mod.render_readme(repo_root=tmp_path)

    assert_that(rendered).contains("lgtm-hq/ai-skills@v9.9.9")
    assert_that(rendered).contains("gh release download v9.9.9")
    assert_that(rendered).does_not_contain("v0.0.1")


def test_render_readme_requires_markers(tmp_path: Path) -> None:
    """A README without skills markers is rejected."""

    mod = _load_generate_readme_module()
    _write_fake_repo(repo_root=tmp_path)
    tmp_path.joinpath("README.md").write_text("# fake\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain"):
        mod.render_readme(repo_root=tmp_path)


def test_first_sentence_keeps_abbreviations() -> None:
    """Sentence splitting does not truncate at lowercase abbreviations."""

    mod = _load_generate_readme_module()

    first = mod._first_sentence(
        "Run checks (e.g. lint) before pushing. Use when asked.",
    )

    assert_that(first).is_equal_to("Run checks (e.g. lint) before pushing.")


def test_repo_readme_is_up_to_date() -> None:
    """Production README.md must match its generated content."""

    mod = _load_generate_readme_module()
    repo_root = Path(__file__).resolve().parents[1]

    rendered = mod.render_readme(repo_root=repo_root)
    existing = (repo_root / "README.md").read_text(encoding="utf-8")

    assert_that(existing).is_equal_to(rendered)
