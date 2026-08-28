"""Tests for the vendor plugin bake pipeline."""

from __future__ import annotations

import json
import tarfile
from io import BytesIO
from pathlib import Path

import bake_vendor_plugins
import pytest
from assertpy import assert_that
from vendor_registry.plugin_version import plugin_version
from vendor_registry.safe_tree import (
    copy_tree,
    replace_directory_contents,
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


def test_check_rejects_symlink_in_baked_output(
    tmp_path: Path,
) -> None:
    """Committed bake output that grows a symlink fails --check."""
    _write_registry(repo_root=tmp_path, plugins_yaml="")
    bake_vendor_plugins.bake(repo_root=tmp_path)
    (tmp_path / "plugins-baked" / "link").symlink_to("COVERAGE.md")

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_replace_keeps_destination_inode(
    tmp_path: Path,
) -> None:
    """Swapping children leaves the plugins-baked directory inode in place."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    marker = dest / "stale.txt"
    marker.write_text("old\n", encoding="utf-8")
    inode = dest.stat().st_ino
    source = tmp_path / "next"
    source.mkdir()
    (source / "COVERAGE.md").write_text("new\n", encoding="utf-8")
    replace_directory_contents(source=source, destination=dest)

    assert_that(dest.stat().st_ino).is_equal_to(inode)
    assert_that((dest / "COVERAGE.md").read_text(encoding="utf-8")).is_equal_to("new\n")
    assert_that(marker.exists()).is_false()


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
