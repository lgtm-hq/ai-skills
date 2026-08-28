"""Tests for the vendor plugin bake pipeline."""

from __future__ import annotations

import json
import tarfile
from io import BytesIO
from pathlib import Path

import bake_vendor_plugins
import pytest
from assertpy import assert_that
from vendor_registry import safe_tree
from vendor_registry.plugin_version import plugin_version
from vendor_registry.safe_tree import (
    copy_tree,
    install_directory,
    validate_tree,
)

_SHA = "0123456789abcdef0123456789abcdef01234567"
_SHORT_SHA = "0123456"


def _write_skill(*, directory: Path, name: str) -> None:
    """Write a minimal SKILL.md into ``directory``.

    Args:
        directory: Skill directory to create.
        name: Frontmatter ``name`` value.
    """
    directory.mkdir(parents=True, exist_ok=True)
    directory.joinpath("SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} skill.\n---\n",
        encoding="utf-8",
    )


def _write_registry(*, repo_root: Path, plugins_yaml: str) -> None:
    """Write an isolated vendors.yaml with one vendor and plugin slices.

    Args:
        repo_root: Isolated repository root.
        plugins_yaml: Indented YAML block for the ``plugins:`` field,
            including the ``plugins:`` key, or an empty string to omit it.
    """
    block = f"    {plugins_yaml}\n" if plugins_yaml else ""
    repo_root.joinpath("vendors.yaml").write_text(
        "---\n"
        "vendors:\n"
        "  - id: example-vendor\n"
        "    repo: owner/example\n"
        f'    sha: "{_SHA}"\n'
        "    displayRef: latest\n"
        "    skillRoots:\n"
        "      - skills\n"
        f"{block}"
        "    license: MIT\n"
        "    homepage: https://github.com/owner/example\n",
        encoding="utf-8",
    )
    repo_root.joinpath("bundles.yaml").write_text(
        "---\n"
        "groups:\n"
        "  git-pr:\n"
        "    id: git-pr\n"
        "    name: Git & PR Workflow\n"
        "    description: First-party plugin.\n"
        "    skills:\n"
        "      - branch\n",
        encoding="utf-8",
    )


def _vendor_tree(tmp_path: Path) -> Path:
    """Create a vendor source tree with skills, extras, and an agent.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        Path to the vendor tree.
    """
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_skill(directory=vendor_root / "skills" / "teach", name="teach")
    _write_skill(directory=vendor_root / "extras" / "bonus", name="bonus")
    nested = vendor_root / "skills" / "alpha" / "examples"
    _write_skill(directory=nested, name="nested-example")
    skipped = vendor_root / "template" / "placeholder"
    _write_skill(directory=skipped, name="placeholder")
    agents = vendor_root / "agents"
    agents.mkdir()
    agents.joinpath("code-reviewer.md").write_text(
        "# code-reviewer\n",
        encoding="utf-8",
    )
    return vendor_root


def test_plugin_version_uses_short_sha_for_latest() -> None:
    """Floating displayRef pins are not versions; bake uses the short SHA."""
    assert_that(
        plugin_version(sha=_SHA, display_ref="latest"),
    ).is_equal_to(_SHORT_SHA)
    assert_that(plugin_version(sha=_SHA, display_ref=None)).is_equal_to(_SHORT_SHA)


def test_plugin_version_uses_display_ref_tag() -> None:
    """A tag displayRef is the pin-derived plugin version."""
    assert_that(
        plugin_version(sha=_SHA, display_ref="v1.2.3"),
    ).is_equal_to("v1.2.3")


def test_bake_emits_empty_marketplace_when_no_plugins(
    tmp_path: Path,
) -> None:
    """Index-only registries still get a committed empty bake output."""
    _write_registry(repo_root=tmp_path, plugins_yaml="")

    bake_vendor_plugins.bake(repo_root=tmp_path)

    baked = tmp_path / "plugins-baked"
    marketplace = json.loads(
        (baked / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"),
    )
    assert_that(marketplace["plugins"]).is_empty()
    coverage = (baked / "COVERAGE.md").read_text(encoding="utf-8")
    assert_that(coverage).contains("No plugin slices are declared")
    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(0)


def test_bake_slices_renames_and_reports_skipped(
    tmp_path: Path,
) -> None:
    """Bake copies declared skills, rewrites frontmatter, and lists skips."""
    vendor_root = _vendor_tree(tmp_path=tmp_path)
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
            "        extraSkills:\n"
            "          - extras/bonus\n"
            "        renameSkills:\n"
            "          teach: teach-example\n"
            "        agents:\n"
            "          - code-reviewer\n"
        ),
    )

    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )

    plugin = tmp_path / "plugins-baked" / "example-plugin"
    alpha = (plugin / "skills" / "alpha" / "SKILL.md").read_text(encoding="utf-8")
    teach = (plugin / "skills" / "teach-example" / "SKILL.md").read_text(
        encoding="utf-8",
    )
    assert_that(alpha).contains("name: alpha")
    assert_that(teach).contains("name: teach-example")
    assert_that((plugin / "skills" / "teach").exists()).is_false()
    assert_that(
        (plugin / "skills" / "alpha" / "examples" / "SKILL.md").is_file(),
    ).is_true()
    assert_that((plugin / "skills" / "bonus" / "SKILL.md").is_file()).is_true()
    assert_that((plugin / "agents" / "code-reviewer.md").is_file()).is_true()
    manifest = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))
    assert_that(manifest["version"]).is_equal_to(_SHORT_SHA)
    assert_that(manifest["name"]).is_equal_to("example-plugin")
    coverage = (tmp_path / "plugins-baked" / "COVERAGE.md").read_text(encoding="utf-8")
    assert_that(coverage).contains("SKIPPED `template/placeholder/SKILL.md`")
    assert_that(coverage).does_not_contain("examples/SKILL.md")
    assert_that(coverage).contains("Global namespace clean")
    marketplace = json.loads(
        (tmp_path / "plugins-baked" / ".claude-plugin" / "marketplace.json").read_text(
            encoding="utf-8",
        ),
    )
    assert_that(marketplace["plugins"][0]["source"]).is_equal_to("./example-plugin")
    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(0)


def test_bake_rejects_symlinks(
    tmp_path: Path,
) -> None:
    """Symlinks in a declared skill tree fail closed."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    (vendor_root / "skills" / "alpha" / "link").symlink_to("SKILL.md")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )

    with pytest.raises(ValueError, match="symlink rejected"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )
    assert_that((tmp_path / "plugins-baked").exists()).is_false()


def test_bake_fails_on_first_party_skill_collision(
    tmp_path: Path,
) -> None:
    """Explode names that match first-party skills/ fail the collision report."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "branch", name="branch")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )
    first_party = tmp_path / "skills" / "branch"
    _write_skill(directory=first_party, name="branch")

    with pytest.raises(ValueError, match="COLLIDES 'branch'"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


def test_bake_fails_on_cross_plugin_skill_collision(
    tmp_path: Path,
) -> None:
    """Two plugins shipping the same explode name fail the collision report."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_skill(directory=vendor_root / "other" / "alpha", name="alpha")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: first-plugin\n"
            "        description: First plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
            "      - id: second-plugin\n"
            "        description: Second plugin.\n"
            "        skillsRoot: other\n"
            '        skills: "*"\n'
        ),
    )

    with pytest.raises(ValueError, match="COLLIDES 'alpha'"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


def test_bake_fails_on_agent_stem_collision(
    tmp_path: Path,
) -> None:
    """The same agent stem in two plugins fails the collision report."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_skill(directory=vendor_root / "other" / "beta", name="beta")
    agents = vendor_root / "agents"
    agents.mkdir()
    agents.joinpath("code-reviewer.md").write_text("# agent\n", encoding="utf-8")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: first-plugin\n"
            "        description: First plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
            "        agents:\n"
            "          - code-reviewer\n"
            "      - id: second-plugin\n"
            "        description: Second plugin.\n"
            "        skillsRoot: other\n"
            '        skills: "*"\n'
            "        agents:\n"
            "          - code-reviewer\n"
        ),
    )

    with pytest.raises(ValueError, match="COLLIDES agent 'code-reviewer'"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


def test_bake_discovers_skills_under_glob_skills_root(
    tmp_path: Path,
) -> None:
    """A glob skillsRoot expands to every matching container."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(
        directory=vendor_root / "plugins" / "one" / "skills" / "alpha",
        name="alpha",
    )
    _write_skill(
        directory=vendor_root / "plugins" / "two" / "skills" / "beta",
        name="beta",
    )
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: glob-plugin\n"
            "        description: Glob skillsRoot plugin.\n"
            "        skillsRoot: plugins/*/skills\n"
            '        skills: "*"\n'
        ),
    )

    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )

    plugin = tmp_path / "plugins-baked" / "glob-plugin"
    assert_that((plugin / "skills" / "alpha" / "SKILL.md").is_file()).is_true()
    assert_that((plugin / "skills" / "beta" / "SKILL.md").is_file()).is_true()


def test_bake_rejects_missing_agent(
    tmp_path: Path,
) -> None:
    """A declared agent stem without agents/<stem>.md fails closed."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
            "        agents:\n"
            "          - missing-agent\n"
        ),
    )

    with pytest.raises(ValueError, match="agent missing"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


def test_bake_rejects_missing_skill(
    tmp_path: Path,
) -> None:
    """A declared skill path without SKILL.md fails closed."""
    vendor_root = tmp_path / "vendor-src"
    (vendor_root / "skills").mkdir(parents=True)
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            "        skills:\n"
            "          - missing\n"
        ),
    )

    with pytest.raises(ValueError, match="missing SKILL.md"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


def test_check_rejects_stale_marketplace(
    tmp_path: Path,
) -> None:
    """--check fails when the committed marketplace does not match."""
    _write_registry(repo_root=tmp_path, plugins_yaml="")
    bake_vendor_plugins.bake(repo_root=tmp_path)
    marketplace = tmp_path / "plugins-baked" / ".claude-plugin" / "marketplace.json"
    marketplace.write_text('{"stale": true}\n', encoding="utf-8")

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_forged_coverage_report(
    tmp_path: Path,
) -> None:
    """--check fails when COVERAGE.md is not the renderer output."""
    _write_registry(repo_root=tmp_path, plugins_yaml="")
    bake_vendor_plugins.bake(repo_root=tmp_path)
    (tmp_path / "plugins-baked" / "COVERAGE.md").write_text(
        "# forged\n",
        encoding="utf-8",
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_stale_display_ref(
    tmp_path: Path,
) -> None:
    """--check fails when displayRef changes without a re-bake."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    registry = tmp_path / "vendors.yaml"
    registry.write_text(
        registry.read_text(encoding="utf-8").replace(
            "displayRef: latest",
            "displayRef: v9.9.9",
        ),
        encoding="utf-8",
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_stale_rename_skills(
    tmp_path: Path,
) -> None:
    """--check fails when renameSkills is added without a re-bake."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "teach", name="teach")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
            "        renameSkills:\n"
            "          teach: teach-renamed\n"
        ),
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_stale_agents(
    tmp_path: Path,
) -> None:
    """--check fails when agents are declared without a re-bake."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    (vendor_root / "agents").mkdir()
    (vendor_root / "agents" / "code-reviewer.md").write_text(
        "# code-reviewer\n",
        encoding="utf-8",
    )
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
            "        agents:\n"
            "          - code-reviewer\n"
        ),
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_tampered_plugin_version(
    tmp_path: Path,
) -> None:
    """--check uses pin-derived versions, not the committed plugin.json."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    manifest_path = tmp_path / "plugins-baked" / "example-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "9.9.9"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_tampered_host_manifest_version(
    tmp_path: Path,
) -> None:
    """--check requires every host adapter plugin.json to match the pin."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    host_manifest = (
        tmp_path / "plugins-baked" / "example-plugin" / ".claude-plugin" / "plugin.json"
    )
    payload = json.loads(host_manifest.read_text(encoding="utf-8"))
    payload["version"] = "9.9.9"
    host_manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_forged_coverage_when_plugins_exist(
    tmp_path: Path,
) -> None:
    """--check hashes plugin-slice coverage, not only index-only reports."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    (tmp_path / "plugins-baked" / "COVERAGE.md").write_text(
        "# forged\n",
        encoding="utf-8",
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_sha_change_under_stable_tag(
    tmp_path: Path,
) -> None:
    """--check fails when the pin SHA changes even if displayRef is a tag."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )
    registry = tmp_path / "vendors.yaml"
    registry.write_text(
        registry.read_text(encoding="utf-8").replace(
            "displayRef: latest",
            "displayRef: v1.2.3",
        ),
        encoding="utf-8",
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    registry.write_text(
        registry.read_text(encoding="utf-8").replace(
            _SHA,
            "ffffffffffffffffffffffffffffffffffffffff",
        ),
        encoding="utf-8",
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_skills_root_change(
    tmp_path: Path,
) -> None:
    """--check fails when skillsRoot changes without a re-bake."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    registry = tmp_path / "vendors.yaml"
    registry.write_text(
        registry.read_text(encoding="utf-8").replace(
            "skillsRoot: skills",
            "skillsRoot: other",
        ),
        encoding="utf-8",
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_removed_rename_skills(
    tmp_path: Path,
) -> None:
    """--check fails when renameSkills is removed without a re-bake."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "teach", name="teach")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
            "        renameSkills:\n"
            "          teach: teach-renamed\n"
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_narrowed_explicit_skills(
    tmp_path: Path,
) -> None:
    """--check fails when an explicit skills list shrinks without a re-bake."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_skill(directory=vendor_root / "skills" / "teach", name="teach")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            "        skills:\n"
            "          - alpha\n"
            "          - teach\n"
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            "        skills:\n"
            "          - alpha\n"
        ),
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_removed_extra_skills(
    tmp_path: Path,
) -> None:
    """--check fails when extraSkills is removed without a re-bake."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_skill(directory=vendor_root / "extras" / "bonus", name="bonus")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
            "        extraSkills:\n"
            "          - extras/bonus\n"
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_unexpected_hooks_in_baked_plugin(
    tmp_path: Path,
) -> None:
    """Hand-added executable hooks in a baked plugin fail --check."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    hooks = tmp_path / "plugins-baked" / "example-plugin" / "hooks"
    hooks.mkdir()
    (hooks / "evil.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_bake_rejects_duplicate_frontmatter_name_keys(
    tmp_path: Path,
) -> None:
    """A second name key cannot bypass the explode-identity check."""
    vendor_root = tmp_path / "vendor-src"
    skill = vendor_root / "skills" / "alpha"
    skill.mkdir(parents=True)
    skill.joinpath("SKILL.md").write_text(
        "---\nname: alpha\nname: branch\n---\n",
        encoding="utf-8",
    )
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )

    with pytest.raises(ValueError, match="duplicate key"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


def test_bake_rejects_frontmatter_name_mismatch(
    tmp_path: Path,
) -> None:
    """Hosts index frontmatter name; a mismatch with the directory fails."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="branch")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )

    with pytest.raises(ValueError, match="does not match directory 'alpha'"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


def test_check_rejects_frontmatter_directory_mismatch(
    tmp_path: Path,
) -> None:
    """--check fails when a baked SKILL.md name disagrees with its directory."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    skill_markdown = (
        tmp_path / "plugins-baked" / "example-plugin" / "skills" / "alpha" / "SKILL.md"
    )
    skill_markdown.write_text(
        "---\nname: branch\ndescription: alpha skill.\n---\n",
        encoding="utf-8",
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_bake_lists_uningested_skill_under_node_modules(
    tmp_path: Path,
) -> None:
    """SKILL.md under node_modules is listed as SKIPPED, not dropped."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    _write_skill(
        directory=vendor_root / "node_modules" / "hidden",
        name="hidden",
    )
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )

    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )

    coverage = (tmp_path / "plugins-baked" / "COVERAGE.md").read_text(
        encoding="utf-8",
    )
    assert_that(coverage).contains("SKIPPED `node_modules/hidden/SKILL.md`")


def test_bake_rejects_symlink_under_node_modules(
    tmp_path: Path,
) -> None:
    """node_modules is not a coverage/validation hole."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    nested = vendor_root / "node_modules" / "pkg"
    nested.mkdir(parents=True)
    (nested / "link").symlink_to("/tmp")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: example-plugin\n"
            "        description: Example vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
        ),
    )

    with pytest.raises(ValueError, match="symlink rejected"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


def test_check_rejects_symlink_in_baked_output(
    tmp_path: Path,
) -> None:
    """Committed bake output that grows a symlink fails --check."""
    _write_registry(repo_root=tmp_path, plugins_yaml="")
    bake_vendor_plugins.bake(repo_root=tmp_path)
    (tmp_path / "plugins-baked" / "link").symlink_to("COVERAGE.md")

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_install_directory_replaces_previous_tree(
    tmp_path: Path,
) -> None:
    """A successful install publishes the staged tree and drops stale files."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    marker = dest / "stale.txt"
    marker.write_text("old\n", encoding="utf-8")
    source = tmp_path / "next"
    source.mkdir()
    (source / "COVERAGE.md").write_text("new\n", encoding="utf-8")
    install_directory(source=source, destination=dest)

    assert_that((dest / "COVERAGE.md").read_text(encoding="utf-8")).is_equal_to(
        "new\n",
    )
    assert_that((dest / "stale.txt").exists()).is_false()


def test_install_directory_does_not_rename_live_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replacing an existing dest must not move it aside with Path.rename."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "COVERAGE.md").write_text("old\n", encoding="utf-8")
    source = tmp_path / "next"
    source.mkdir()
    (source / "COVERAGE.md").write_text("new\n", encoding="utf-8")

    def _forbidden_rename(self: Path, target: Path | str) -> Path:
        """Fail if the live destination is renamed aside.

        Args:
            self: Path being renamed.
            target: Rename destination.

        Returns:
            Never returns.

        Raises:
            AssertionError: Always; dest must stay at its path.
        """
        msg = "Path.rename must not move the live destination aside"
        raise AssertionError(msg)

    monkeypatch.setattr(Path, "rename", _forbidden_rename)
    install_directory(source=source, destination=dest)

    assert_that(dest.is_dir()).is_true()
    assert_that((dest / "COVERAGE.md").read_text(encoding="utf-8")).is_equal_to(
        "new\n",
    )


def test_install_directory_leaves_previous_tree_on_exchange_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed atomic exchange must not remove plugins-baked."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "COVERAGE.md").write_text("old\n", encoding="utf-8")
    source = tmp_path / "next"
    source.mkdir()
    (source / "COVERAGE.md").write_text("new\n", encoding="utf-8")

    def _fail_exchange(*, first: Path, second: Path) -> None:
        """Inject an exchange failure.

        Args:
            first: Staged tree.
            second: Live destination.

        Raises:
            OSError: Always.
        """
        msg = "injected exchange failure"
        raise OSError(msg)

    monkeypatch.setattr(safe_tree, "_exchange_paths", _fail_exchange)

    with pytest.raises(OSError, match="injected exchange failure"):
        install_directory(source=source, destination=dest)

    assert_that((dest / "COVERAGE.md").read_text(encoding="utf-8")).is_equal_to(
        "old\n",
    )


def test_extract_tarball_strips_root_and_rejects_escape(
    tmp_path: Path,
) -> None:
    """GitHub tarball members drop the repo-sha prefix and reject ``..``."""
    dest = tmp_path / "unpacked"
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        skill = tarfile.TarInfo(name="repo-sha/skills/alpha/SKILL.md")
        payload = b"---\nname: alpha\n---\n"
        skill.size = len(payload)
        archive.addfile(tarinfo=skill, fileobj=BytesIO(payload))
    bake_vendor_plugins._extract_tarball(payload=buffer.getvalue(), dest=dest)
    assert_that((dest / "skills" / "alpha" / "SKILL.md").is_file()).is_true()

    evil = BytesIO()
    with tarfile.open(fileobj=evil, mode="w:gz") as archive:
        member = tarfile.TarInfo(name="repo-sha/../outside.txt")
        member.size = 1
        archive.addfile(tarinfo=member, fileobj=BytesIO(b"x"))
    with pytest.raises(ValueError, match="path escape rejected"):
        bake_vendor_plugins._extract_tarball(
            payload=evil.getvalue(),
            dest=tmp_path / "evil",
        )


def test_copy_tree_rejects_path_escape(
    tmp_path: Path,
) -> None:
    """Copying a directory outside the vendor root fails closed."""
    vendor_root = tmp_path / "vendor"
    vendor_root.mkdir()
    outside = tmp_path / "outside"
    _write_skill(directory=outside, name="escaped")

    with pytest.raises(ValueError, match="path escape rejected"):
        copy_tree(
            source=outside,
            destination=tmp_path / "dest",
            source_root=vendor_root,
        )


def test_validate_tree_rejects_symlink(
    tmp_path: Path,
) -> None:
    """Tree validation fails closed on a symlink anywhere in the tree."""
    root = tmp_path / "tree"
    root.mkdir()
    (root / "file.txt").write_text("ok\n", encoding="utf-8")
    (root / "link").symlink_to("file.txt")

    with pytest.raises(ValueError, match="symlink rejected"):
        validate_tree(root=root)


def test_main_check_returns_zero_for_empty_bake(
    tmp_path: Path,
) -> None:
    """CLI --check succeeds for a freshly baked index-only registry."""
    _write_registry(repo_root=tmp_path, plugins_yaml="")
    assert_that(
        bake_vendor_plugins.main(["--repo-root", str(tmp_path)]),
    ).is_equal_to(0)
    assert_that(
        bake_vendor_plugins.main(["--check", "--repo-root", str(tmp_path)]),
    ).is_equal_to(0)
