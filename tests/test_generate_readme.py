"""Tests for ``scripts/generate_readme.py``."""

from __future__ import annotations

import importlib.util
import json
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
    id: core
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
        "The npm version matches the git release tag "
        "(`@0.0.1` ↔ `v0.0.1`):\n\n"
        "```bash\nbunx --package=@lgtm-hq/ai-skills@0.0.1 skill\n"
        "bunx skills add lgtm-hq/ai-skills@v0.0.1 -g\n"
        "gh release download v0.0.1 -R lgtm-hq/ai-skills\n```\n\n"
        "## Plugins\n\n"
        "<!-- plugins:start -->\nstale\n<!-- plugins:end -->\n\n"
        "## License\n",
        encoding="utf-8",
    )


def test_render_readme_builds_plugin_table(tmp_path: Path) -> None:
    """Groups render as a plugin table with ids and skill links."""

    mod = _load_generate_readme_module()
    _write_fake_repo(repo_root=tmp_path)

    rendered = mod.render_readme(repo_root=tmp_path)

    assert_that(rendered).contains("| Plugin | Id | Description | Skills |")
    assert_that(rendered).contains("| Core Workflow | `core` |")
    assert_that(rendered).contains("Everyday workflow skills.")
    assert_that(rendered).contains("[alpha](skills/alpha/SKILL.md)")
    assert_that(rendered).does_not_contain("Use when asked for alpha.")
    assert_that(rendered).does_not_contain("stale")


def test_render_readme_omits_ungrouped_from_plugin_table(tmp_path: Path) -> None:
    """Ungrouped skills are noted, not listed as marketplace plugins."""

    mod = _load_generate_readme_module()
    _write_fake_repo(repo_root=tmp_path)

    rendered = mod.render_readme(repo_root=tmp_path)

    assert_that(rendered).contains(
        "Skills listed under `ungrouped` in `bundles.yaml` "
        "are not marketplace plugins.",
    )
    assert_that(rendered).does_not_contain("### Other")
    assert_that(rendered).does_not_contain("| `beta` |")
    assert_that(rendered).does_not_contain("[beta](skills/beta/SKILL.md)")


def test_render_readme_omits_ungrouped_note_when_empty(tmp_path: Path) -> None:
    """An empty ungrouped list does not emit the marketplace-plugin note."""

    mod = _load_generate_readme_module()
    _write_fake_repo(repo_root=tmp_path)
    tmp_path.joinpath("bundles.yaml").write_text(
        """
groups:
  core:
    id: core
    name: Core Workflow
    description: Everyday workflow skills.
    skills:
      - alpha
      - beta
ungrouped: []
""",
        encoding="utf-8",
    )

    rendered = mod.render_readme(repo_root=tmp_path)

    assert_that(rendered).does_not_contain(
        "Skills listed under `ungrouped` in `bundles.yaml` "
        "are not marketplace plugins.",
    )
    assert_that(rendered).contains("[beta](skills/beta/SKILL.md)")


def test_repo_readme_install_paths_are_plugin_level() -> None:
    """Production README documents host plugin installs, not skill cherry-picks."""

    readme = (
        Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("README.md")
        .read_text(
            encoding="utf-8",
        )
    )

    assert_that(readme).contains(
        "claude plugin marketplace add lgtm-hq/ai-skills@v",
    )
    assert_that(readme).contains("claude plugin install git-pr@ai-skills")
    assert_that(readme).contains("copilot plugin marketplace add lgtm-hq/ai-skills")
    assert_that(readme).contains("copilot plugin install git-pr@ai-skills")
    assert_that(readme).contains("sk install -y --global -a cursor --bundle review")
    assert_that(readme).contains("git clone https://github.com/lgtm-hq/ai-skills.git")
    assert_that(readme).contains("~/.cursor/plugins/local/ai-skills")
    assert_that(readme).contains("Harness-agnostic by construction")
    assert_that(readme).does_not_contain("--skill")
    assert_that(readme).does_not_contain("--all")
    assert_that(readme).does_not_contain("Toggle skills")
    assert_that(readme).does_not_contain("The seven first-party plugins")


def test_repo_readme_plugin_suffix_matches_marketplace_name() -> None:
    """Host install suffixes match the generated Claude marketplace name."""

    repo_root = Path(__file__).resolve().parents[1]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    marketplace_path = repo_root / ".claude-plugin" / "marketplace.json"
    marketplace = json.loads(
        marketplace_path.read_text(encoding="utf-8"),
    )
    name = str(marketplace["name"])

    assert_that(readme).contains(f"claude plugin install git-pr@{name}")
    assert_that(readme).contains(f"copilot plugin install git-pr@{name}")
    assert_that(readme).contains(f"~/.cursor/plugins/local/{name}")


def test_render_readme_syncs_version_pins_to_pyproject(tmp_path: Path) -> None:
    """Release-tag pins are rewritten to the pyproject.toml version."""

    mod = _load_generate_readme_module()
    _write_fake_repo(repo_root=tmp_path)

    rendered = mod.render_readme(repo_root=tmp_path)

    assert_that(rendered).contains("@lgtm-hq/ai-skills@9.9.9")
    assert_that(rendered).contains("lgtm-hq/ai-skills@v9.9.9")
    assert_that(rendered).contains("gh release download v9.9.9")
    assert_that(rendered).contains("`@9.9.9` ↔ `v9.9.9`")
    assert_that(rendered).does_not_contain("v0.0.1")
    assert_that(rendered).does_not_contain("@lgtm-hq/ai-skills@0.0.1")
    assert_that(rendered).does_not_contain("`@0.0.1` ↔ `v0.0.1`")


def test_render_readme_requires_markers(tmp_path: Path) -> None:
    """A README without plugin markers is rejected."""

    mod = _load_generate_readme_module()
    _write_fake_repo(repo_root=tmp_path)
    tmp_path.joinpath("README.md").write_text("# fake\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain"):
        mod.render_readme(repo_root=tmp_path)


def test_render_readme_table_cells_are_single_line(tmp_path: Path) -> None:
    """Plugin table cells collapse YAML newlines and escape pipes."""

    mod = _load_generate_readme_module()
    _write_fake_repo(repo_root=tmp_path)
    tmp_path.joinpath("bundles.yaml").write_text(
        """
groups:
  core:
    id: core
    name: |
      Core | Workflow
    description: |
      Everyday | workflow
      skills.
    skills:
      - alpha
ungrouped:
  - beta
""",
        encoding="utf-8",
    )

    rendered = mod.render_readme(repo_root=tmp_path)

    assert_that(rendered).contains(
        "| Core \\| Workflow | `core` | Everyday \\| workflow skills. |",
    )
    assert_that(rendered).does_not_contain("Everyday | workflow\n")
    assert_that(rendered).does_not_contain("Core | Workflow\n")


def test_repo_readme_is_up_to_date() -> None:
    """Production README.md must match its generated content."""

    mod = _load_generate_readme_module()
    repo_root = Path(__file__).resolve().parents[1]

    rendered = mod.render_readme(repo_root=repo_root)
    existing = (repo_root / "README.md").read_text(encoding="utf-8")

    assert_that(existing).is_equal_to(rendered)
