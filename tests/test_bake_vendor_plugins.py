"""Tests for the vendor plugin bake pipeline."""

from __future__ import annotations

import hashlib
import json
import os
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
    assert_that(plugin_version(sha=_SHA, display_ref="main")).is_equal_to(_SHORT_SHA)
    assert_that(plugin_version(sha=_SHA, display_ref="HEAD")).is_equal_to(_SHORT_SHA)
    assert_that(plugin_version(sha=_SHA, display_ref="master")).is_equal_to(
        _SHORT_SHA,
    )
    assert_that(
        plugin_version(sha=_SHA, display_ref="v1.2-not-a-version"),
    ).is_equal_to(_SHORT_SHA)
    assert_that(plugin_version(sha=_SHA, display_ref="v1.2")).is_equal_to(
        _SHORT_SHA,
    )


def test_plugin_version_uses_display_ref_tag() -> None:
    """A tag displayRef is the pin-derived plugin version."""
    assert_that(
        plugin_version(sha=_SHA, display_ref="v1.2.3"),
    ).is_equal_to("v1.2.3")
    assert_that(
        plugin_version(sha=_SHA, display_ref="1.2.3"),
    ).is_equal_to("1.2.3")
    assert_that(
        plugin_version(sha=_SHA, display_ref="v1.2.3-rc.1"),
    ).is_equal_to("v1.2.3-rc.1")


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


def test_check_rejects_stale_repo(
    tmp_path: Path,
) -> None:
    """--check fails when vendors.yaml repo changes without a re-bake."""
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
            "repo: owner/example",
            "repo: owner/different",
        ),
        encoding="utf-8",
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_coverage_and_lock_digest_forge(
    tmp_path: Path,
) -> None:
    """Updating COVERAGE.md together with BAKE.json digests still fails."""
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
    coverage_path = tmp_path / "plugins-baked" / "COVERAGE.md"
    forged = "# forged\n"
    coverage_path.write_text(forged, encoding="utf-8")
    digest = hashlib.sha256(forged.encode(encoding="utf-8")).hexdigest()
    lock_path = tmp_path / "plugins-baked" / "BAKE.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["coverageSha256"] = digest
    lock["files"]["COVERAGE.md"] = digest
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_forged_coverage_inputs(
    tmp_path: Path,
) -> None:
    """Invented ingest stats in COVERAGE.md plus BAKE.json still fail."""
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
    coverage_path = tmp_path / "plugins-baked" / "COVERAGE.md"
    forged = coverage_path.read_text(encoding="utf-8").replace(
        "1 ingested, 0 SKILL.md skipped",
        "99 ingested, 0 SKILL.md skipped",
    )
    coverage_path.write_text(forged, encoding="utf-8")
    digest = hashlib.sha256(forged.encode(encoding="utf-8")).hexdigest()
    lock_path = tmp_path / "plugins-baked" / "BAKE.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["coverageSha256"] = digest
    lock["files"]["COVERAGE.md"] = digest
    lock["coverageInputs"]["ingestedCounts"]["example-vendor"] = 99
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_accepts_overlapping_renamed_slices(
    tmp_path: Path,
) -> None:
    """Two plugins may ingest the same source skill when one is renamed."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "shared", name="shared")
    _write_registry(
        repo_root=tmp_path,
        plugins_yaml=(
            "plugins:\n"
            "      - id: plugin-a\n"
            "        description: First overlapping slice.\n"
            "        skillsRoot: skills\n"
            "        skills:\n"
            "          - shared\n"
            "      - id: plugin-b\n"
            "        description: Second overlapping slice.\n"
            "        skillsRoot: skills\n"
            "        skills:\n"
            "          - shared\n"
            "        renameSkills:\n"
            "          shared: shared-renamed\n"
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    coverage = (tmp_path / "plugins-baked" / "COVERAGE.md").read_text(
        encoding="utf-8",
    )

    assert_that(coverage).contains("2 ingested")
    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(0)


def test_bake_rejects_missing_internal_markdown_link(
    tmp_path: Path,
) -> None:
    """Relative markdown links must resolve to a file inside the plugin."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    skill = vendor_root / "skills" / "alpha" / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8") + "See [shared](../../shared.md).\n",
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

    with pytest.raises(ValueError, match="internal reference missing"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


def test_bake_rejects_escaping_internal_markdown_link(
    tmp_path: Path,
) -> None:
    """Markdown links must not escape the baked plugin directory."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    skill = vendor_root / "skills" / "alpha" / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8") + "See [out](../../../outside.md).\n",
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

    with pytest.raises(ValueError, match="path escape rejected"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


def test_bake_rejects_reference_style_markdown_link(
    tmp_path: Path,
) -> None:
    """Reference-style markdown definitions are validated like inline links."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    skill = vendor_root / "skills" / "alpha" / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8")
        + "See [shared][doc].\n\n[doc]: ../../shared.md\n",
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

    with pytest.raises(ValueError, match="internal reference missing"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


def test_bake_rejects_multiline_reference_style_markdown_link(
    tmp_path: Path,
) -> None:
    """CommonMark allows one line ending between the colon and destination."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    skill = vendor_root / "skills" / "alpha" / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8")
        + "See [shared][doc].\n\n[doc]:\n ../../shared.md\n",
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

    with pytest.raises(ValueError, match="internal reference missing"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


@pytest.mark.parametrize(
    ("suffix", "message"),
    [
        pytest.param(
            "See [shared `code ] here`](../../../outside.md).\n",
            "path escape rejected",
            id="code-span-label",
        ),
        pytest.param(
            "See [shared\ndoc](../../../outside.md).\n",
            "path escape rejected",
            id="wrapped-link-text",
        ),
        pytest.param(
            "See [x](%2e%2e/%2e%2e/%2e%2e/outside.md).\n",
            "path escape rejected",
            id="percent-encoded-escape",
        ),
        pytest.param(
            "See [x][doc].\n\n[doc]: <safe missing.md>\n",
            "internal reference missing",
            id="angle-dest-spaces",
        ),
        pytest.param(
            "> [doc]: ../../shared.md\n",
            "internal reference missing",
            id="blockquote-ref-def",
        ),
        pytest.param(
            "See [x](..\\..\\outside.md).\n",
            "path escape rejected",
            id="backslash-path",
        ),
        pytest.param(
            "See [x](file:../../../outside.md).\n",
            "path escape rejected",
            id="file-scheme",
        ),
        pytest.param(
            "See [x](javascript:alert(1)).\n",
            "path escape rejected",
            id="javascript-scheme",
        ),
        pytest.param(
            "See [x](vbscript:foo).\n",
            "path escape rejected",
            id="vbscript-scheme",
        ),
    ],
)
def test_bake_rejects_commonmark_markdown_link_forms(
    tmp_path: Path,
    suffix: str,
    message: str,
) -> None:
    """CommonMark destinations are parsed, not guessed with regex."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    skill = vendor_root / "skills" / "alpha" / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8") + suffix,
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

    with pytest.raises(ValueError, match=message):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


def test_bake_rejects_query_string_decoy_markdown_target(
    tmp_path: Path,
) -> None:
    """Query components are not filename characters."""
    vendor_root = tmp_path / "vendor-src"
    skill_dir = vendor_root / "skills" / "alpha"
    _write_skill(directory=skill_dir, name="alpha")
    (skill_dir / "missing.md?raw=1").write_text("decoy\n", encoding="utf-8")
    skill = skill_dir / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8") + "See [x](missing.md?raw=1).\n",
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

    with pytest.raises(ValueError, match="internal reference missing"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


def test_bake_rejects_nested_bracket_markdown_link(
    tmp_path: Path,
) -> None:
    """CommonMark link text may contain nested balanced brackets."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
    skill = vendor_root / "skills" / "alpha" / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8")
        + "See [shared [nested]](../../../outside.md).\n",
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

    with pytest.raises(ValueError, match="path escape rejected"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param(
            "See [shared [nested]](../../../outside.md).\n",
            id="nested-brackets",
        ),
        pytest.param(
            "See [shared `code ] here`](../../../outside.md).\n",
            id="code-span-label",
        ),
        pytest.param(
            "> [doc]: ../../shared.md\n",
            id="blockquote-ref-def",
        ),
        pytest.param(
            "See [x][doc].\n\n[doc]: <safe missing.md>\n",
            id="angle-dest-spaces",
        ),
    ],
)
def test_check_rejects_commonmark_markdown_links(
    tmp_path: Path,
    suffix: str,
) -> None:
    """Offline --check rejects CommonMark destinations, not only hashes."""
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
    skill = (
        tmp_path / "plugins-baked" / "example-plugin" / "skills" / "alpha" / "SKILL.md"
    )
    skill.write_text(
        skill.read_text(encoding="utf-8") + suffix,
        encoding="utf-8",
    )
    relative = "example-plugin/skills/alpha/SKILL.md"
    digest = hashlib.sha256(skill.read_bytes()).hexdigest()
    lock_path = tmp_path / "plugins-baked" / "BAKE.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["files"][relative] = digest
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_query_string_decoy_markdown_target(
    tmp_path: Path,
) -> None:
    """Offline --check ignores query-named decoy files even after digest rewrite."""
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
    skill_dir = tmp_path / "plugins-baked" / "example-plugin" / "skills" / "alpha"
    decoy = skill_dir / "missing.md?raw=1"
    decoy.write_text("decoy\n", encoding="utf-8")
    skill = skill_dir / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8") + "See [x](missing.md?raw=1).\n",
        encoding="utf-8",
    )
    lock_path = tmp_path / "plugins-baked" / "BAKE.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["files"] = bake_vendor_plugins._baked_file_digests(
        baked_root=tmp_path / "plugins-baked",
    )
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_extra_bake_lock_keys(
    tmp_path: Path,
) -> None:
    """BAKE.json metadata and shape are allowlisted."""
    _write_registry(repo_root=tmp_path, plugins_yaml="")
    bake_vendor_plugins.bake(repo_root=tmp_path)
    lock_path = tmp_path / "plugins-baked" / "BAKE.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["extra"] = True
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_non_mapping_bake_lock(
    tmp_path: Path,
) -> None:
    """A JSON array BAKE.json fails closed instead of AttributeError."""
    _write_registry(repo_root=tmp_path, plugins_yaml="")
    bake_vendor_plugins.bake(repo_root=tmp_path)
    (tmp_path / "plugins-baked" / "BAKE.json").write_text(
        "[]\n",
        encoding="utf-8",
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_unexpected_root_and_marketplace_files(
    tmp_path: Path,
) -> None:
    """--check allowlists plugins-baked root and the marketplace directory."""
    _write_registry(repo_root=tmp_path, plugins_yaml="")
    bake_vendor_plugins.bake(repo_root=tmp_path)
    (tmp_path / "plugins-baked" / ".evil").mkdir()
    (tmp_path / "plugins-baked" / ".evil" / "x").write_text("p\n", encoding="utf-8")

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)

    bake_vendor_plugins.bake(repo_root=tmp_path)
    (tmp_path / "plugins-baked" / ".claude-plugin" / "hooks.json").write_text(
        "{}\n", encoding="utf-8"
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


def test_check_rejects_missing_empty_skills_directory(
    tmp_path: Path,
) -> None:
    """Agent-only plugins still require the empty baked skills/ directory."""
    vendor_root = tmp_path / "vendor-src"
    (vendor_root / "skills").mkdir(parents=True)
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
            "        agents:\n"
            "          - code-reviewer\n"
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    skills = tmp_path / "plugins-baked" / "example-plugin" / "skills"
    assert_that(skills.is_dir()).is_true()
    assert_that(any(skills.iterdir())).is_false()
    skills.rmdir()

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


def test_check_rejects_deleted_wildcard_skill(
    tmp_path: Path,
) -> None:
    """--check fails when a wildcard-selected skill is removed from disk."""
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
            '        skills: "*"\n'
        ),
    )
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    skill = tmp_path / "plugins-baked" / "example-plugin" / "skills" / "teach"
    skill.joinpath("SKILL.md").unlink()
    skill.rmdir()

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_injected_undeclared_skill(
    tmp_path: Path,
) -> None:
    """--check fails when an extra skill directory is added after bake."""
    vendor_root = tmp_path / "vendor-src"
    _write_skill(directory=vendor_root / "skills" / "alpha", name="alpha")
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
    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )
    _write_skill(
        directory=tmp_path / "plugins-baked" / "example-plugin" / "skills" / "teach",
        name="teach",
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_modified_skill_body(
    tmp_path: Path,
) -> None:
    """--check fails when a baked SKILL.md body is edited."""
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
        skill_markdown.read_text(encoding="utf-8") + "# edited\n",
        encoding="utf-8",
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_extra_generated_files(
    tmp_path: Path,
) -> None:
    """--check fails when unexpected files appear in plugins-baked."""
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
    (tmp_path / "plugins-baked" / "evil.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "plugins-baked" / "example-plugin" / "skills" / "evil.sh").write_text(
        "#!/bin/sh\n", encoding="utf-8"
    )

    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_bake_rejects_unused_rename_skills(
    tmp_path: Path,
) -> None:
    """A renameSkills entry that matches no ingested skill fails bake."""
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
            "        renameSkills:\n"
            "          ghost: renamed-ghost\n"
        ),
    )

    with pytest.raises(ValueError, match="unused renameSkills 'ghost'"):
        bake_vendor_plugins.bake(
            repo_root=tmp_path,
            vendor_trees={"example-vendor": vendor_root},
        )


def test_bake_renames_quoted_frontmatter_name_key(
    tmp_path: Path,
) -> None:
    """Quoted YAML name keys are rewritten during renameSkills."""
    vendor_root = tmp_path / "vendor-src"
    skill = vendor_root / "skills" / "teach"
    skill.mkdir(parents=True)
    skill.joinpath("SKILL.md").write_text(
        '---\n"name": teach\ndescription: teach skill.\n---\n',
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
            "        renameSkills:\n"
            "          teach: teach-renamed\n"
        ),
    )

    bake_vendor_plugins.bake(
        repo_root=tmp_path,
        vendor_trees={"example-vendor": vendor_root},
    )

    rewritten = (
        tmp_path
        / "plugins-baked"
        / "example-plugin"
        / "skills"
        / "teach-renamed"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert_that(rewritten).contains("name: teach-renamed")
    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(0)


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

    original_rename = Path.rename

    def _forbidden_rename(self: Path, target: Path | str) -> Path:
        """Fail if the live destination directory itself is renamed.

        Args:
            self: Path being renamed.
            target: Rename destination.

        Returns:
            The renamed path when ``self`` is not the live destination.

        Raises:
            AssertionError: If the live destination directory is renamed.
        """
        if self.resolve() == dest.resolve():
            msg = "Path.rename must not move the live destination aside"
            raise AssertionError(msg)
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", _forbidden_rename)
    dest_inode = dest.stat().st_ino
    install_directory(source=source, destination=dest)

    assert_that(dest.is_dir()).is_true()
    assert_that(dest.stat().st_ino).is_equal_to(dest_inode)
    assert_that((dest / "COVERAGE.md").read_text(encoding="utf-8")).is_equal_to(
        "new\n",
    )


def test_install_directory_restores_complete_tree_on_mirror_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed inode mirror restores the original dest inode and cwd."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "a.txt").write_text("old-a\n", encoding="utf-8")
    (dest / "b.txt").write_text("old-b\n", encoding="utf-8")
    source = tmp_path / "next"
    source.mkdir()
    (source / "a.txt").write_text("new-a\n", encoding="utf-8")
    (source / "b.txt").write_text("new-b\n", encoding="utf-8")
    dest_inode = dest.stat().st_ino

    def _fail_mirror(*, source: Path, destination: Path) -> None:
        """Inject a failure after the destination path already holds the new tree.

        Args:
            source: Staged tree now at the live path.
            destination: Original destination inode.

        Raises:
            OSError: Always.
        """
        msg = "injected mirror failure"
        raise OSError(msg)

    monkeypatch.setattr(safe_tree, "_mirror_tree", _fail_mirror)
    previous_cwd = Path.cwd()
    try:
        os.chdir(dest)
        with pytest.raises(OSError, match="injected mirror failure"):
            install_directory(source=source, destination=dest)
        Path("probe.txt").write_text("ok\n", encoding="utf-8")
        assert_that(Path.cwd().resolve()).is_equal_to(dest.resolve())
    finally:
        os.chdir(previous_cwd)

    assert_that(dest.stat().st_ino).is_equal_to(dest_inode)
    assert_that((dest / "a.txt").read_text(encoding="utf-8")).is_equal_to(
        "old-a\n",
    )
    assert_that((dest / "b.txt").read_text(encoding="utf-8")).is_equal_to(
        "old-b\n",
    )
    assert_that((dest / "probe.txt").read_text(encoding="utf-8")).is_equal_to(
        "ok\n",
    )
    assert_that((tmp_path / ".plugins-baked.bak").exists()).is_false()
    assert_that((tmp_path / ".plugins-baked.hold").exists()).is_false()


def test_install_directory_restores_complete_tree_on_partial_mirror_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial inode mirror must restore the complete original tree."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "a.txt").write_text("old-a\n", encoding="utf-8")
    (dest / "b.txt").write_text("old-b\n", encoding="utf-8")
    source = tmp_path / "next"
    source.mkdir()
    (source / "a.txt").write_text("new-a\n", encoding="utf-8")
    (source / "b.txt").write_text("new-b\n", encoding="utf-8")
    dest_inode = dest.stat().st_ino

    def _partial_mirror(*, source: Path, destination: Path) -> None:
        """Copy one file onto the original inode, then fail.

        Args:
            source: Staged tree now at the live path.
            destination: Original destination inode.

        Raises:
            OSError: After the first file copy.
        """
        first = min(
            (path for path in source.iterdir() if path.is_file()),
            key=lambda path: path.name,
        )
        safe_tree._copy_file_nofollow(
            source=first,
            destination=destination / first.name,
        )
        msg = "injected partial mirror failure"
        raise OSError(msg)

    monkeypatch.setattr(safe_tree, "_mirror_tree", _partial_mirror)
    previous_cwd = Path.cwd()
    try:
        os.chdir(dest)
        with pytest.raises(OSError, match="injected partial mirror failure"):
            install_directory(source=source, destination=dest)
        Path("probe.txt").write_text("ok\n", encoding="utf-8")
        assert_that(Path.cwd().resolve()).is_equal_to(dest.resolve())
    finally:
        os.chdir(previous_cwd)

    assert_that(dest.stat().st_ino).is_equal_to(dest_inode)
    assert_that((dest / "a.txt").read_text(encoding="utf-8")).is_equal_to(
        "old-a\n",
    )
    assert_that((dest / "b.txt").read_text(encoding="utf-8")).is_equal_to(
        "old-b\n",
    )
    assert_that((dest / "probe.txt").read_text(encoding="utf-8")).is_equal_to(
        "ok\n",
    )
    assert_that((tmp_path / ".plugins-baked.hold").exists()).is_false()


def test_install_directory_preserves_inode_when_rollback_exchange_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed rollback exchange must not unlink the original cwd inode."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "a.txt").write_text("old-a\n", encoding="utf-8")
    source = tmp_path / "next"
    source.mkdir()
    (source / "a.txt").write_text("new-a\n", encoding="utf-8")
    dest_inode = dest.stat().st_ino
    real_exchange = safe_tree._exchange_paths
    calls = {"count": 0}

    def _fail_mirror(*, source: Path, destination: Path) -> None:
        """Fail after the destination path already holds the new tree.

        Args:
            source: Staged tree now at the live path.
            destination: Original destination inode.

        Raises:
            OSError: Always.
        """
        del source, destination
        msg = "injected mirror failure"
        raise OSError(msg)

    def _fail_second_exchange(*, first: Path, second: Path) -> None:
        """Fail the rollback exchange after the first swap succeeded.

        Args:
            first: First path.
            second: Second path.

        Raises:
            OSError: On the second exchange call.
        """
        calls["count"] += 1
        if calls["count"] == 2:
            msg = "injected exchange failure"
            raise OSError(msg)
        real_exchange(first=first, second=second)

    monkeypatch.setattr(safe_tree, "_mirror_tree", _fail_mirror)
    monkeypatch.setattr(safe_tree, "_exchange_paths", _fail_second_exchange)
    previous_cwd = Path.cwd()
    try:
        os.chdir(dest)
        with pytest.raises(ExceptionGroup, match="bake destination publish"):
            install_directory(source=source, destination=dest)
        cwd = Path.cwd()
        assert_that(cwd.exists()).is_true()
        assert_that(cwd.stat().st_ino).is_equal_to(dest_inode)
    finally:
        os.chdir(previous_cwd)

    assert_that((tmp_path / ".plugins-baked.hold").exists()).is_true()


def test_install_directory_restores_on_snapshot_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed snapshot copy must swap the untouched original inode back."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "a.txt").write_text("old-a\n", encoding="utf-8")
    source = tmp_path / "next"
    source.mkdir()
    (source / "a.txt").write_text("new-a\n", encoding="utf-8")
    dest_inode = dest.stat().st_ino
    real_replace = safe_tree._replace_tree_contents
    calls = {"count": 0}

    def _fail_first_replace(*, source: Path, destination: Path) -> None:
        """Fail the snapshot copy and otherwise defer to the real helper.

        Args:
            source: Tree being copied.
            destination: Copy destination.

        Raises:
            OSError: On the first call.
        """
        calls["count"] += 1
        if calls["count"] == 1:
            msg = "injected snapshot failure"
            raise OSError(msg)
        real_replace(source=source, destination=destination)

    monkeypatch.setattr(safe_tree, "_replace_tree_contents", _fail_first_replace)
    previous_cwd = Path.cwd()
    try:
        os.chdir(dest)
        with pytest.raises(OSError, match="injected snapshot failure"):
            install_directory(source=source, destination=dest)
        Path("probe.txt").write_text("ok\n", encoding="utf-8")
        assert_that(Path.cwd().resolve()).is_equal_to(dest.resolve())
    finally:
        os.chdir(previous_cwd)

    assert_that(dest.stat().st_ino).is_equal_to(dest_inode)
    assert_that((dest / "a.txt").read_text(encoding="utf-8")).is_equal_to(
        "old-a\n",
    )
    assert_that((dest / "probe.txt").read_text(encoding="utf-8")).is_equal_to(
        "ok\n",
    )
    assert_that((tmp_path / ".plugins-baked.hold").exists()).is_false()


def test_install_directory_restores_after_interrupt_on_first_exchange(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt after the first swap must still restore the original inode."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "a.txt").write_text("old-a\n", encoding="utf-8")
    source = tmp_path / "next"
    source.mkdir()
    (source / "a.txt").write_text("new-a\n", encoding="utf-8")
    dest_inode = dest.stat().st_ino
    real_exchange = safe_tree._exchange_paths
    calls = {"count": 0}

    def _interrupt_first(*, first: Path, second: Path) -> None:
        """Swap paths, then interrupt after the opening exchange.

        Args:
            first: First path.
            second: Second path.

        Raises:
            KeyboardInterrupt: After the first successful swap.
        """
        real_exchange(first=first, second=second)
        calls["count"] += 1
        if calls["count"] == 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(safe_tree, "_exchange_paths", _interrupt_first)
    previous_cwd = Path.cwd()
    try:
        os.chdir(dest)
        with pytest.raises(KeyboardInterrupt):
            install_directory(source=source, destination=dest)
        Path("probe.txt").write_text("ok\n", encoding="utf-8")
        assert_that(Path.cwd().resolve()).is_equal_to(dest.resolve())
    finally:
        os.chdir(previous_cwd)

    assert_that(dest.stat().st_ino).is_equal_to(dest_inode)
    assert_that((dest / "a.txt").read_text(encoding="utf-8")).is_equal_to(
        "old-a\n",
    )
    assert_that((tmp_path / ".plugins-baked.hold").exists()).is_false()


def test_install_directory_keeps_publish_after_interrupt_on_closing_exchange(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt after the closing swap must not undo a finished publish."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "a.txt").write_text("old-a\n", encoding="utf-8")
    source = tmp_path / "next"
    source.mkdir()
    (source / "a.txt").write_text("new-a\n", encoding="utf-8")
    dest_inode = dest.stat().st_ino
    real_exchange = safe_tree._exchange_paths
    calls = {"count": 0}

    def _interrupt_second(*, first: Path, second: Path) -> None:
        """Swap paths, then interrupt after the closing exchange.

        Args:
            first: First path.
            second: Second path.

        Raises:
            KeyboardInterrupt: After the second successful swap.
        """
        real_exchange(first=first, second=second)
        calls["count"] += 1
        if calls["count"] == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(safe_tree, "_exchange_paths", _interrupt_second)
    previous_cwd = Path.cwd()
    try:
        os.chdir(dest)
        with pytest.raises(KeyboardInterrupt):
            install_directory(source=source, destination=dest)
        Path("probe.txt").write_text("ok\n", encoding="utf-8")
        assert_that(Path.cwd().resolve()).is_equal_to(dest.resolve())
    finally:
        os.chdir(previous_cwd)

    assert_that(dest.stat().st_ino).is_equal_to(dest_inode)
    assert_that((dest / "a.txt").read_text(encoding="utf-8")).is_equal_to(
        "new-a\n",
    )
    assert_that((tmp_path / ".plugins-baked.hold").exists()).is_false()


def test_install_directory_surfaces_hold_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed hold cleanup must not hide a leftover sidecar from --check."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "a.txt").write_text("old-a\n", encoding="utf-8")
    source = tmp_path / "next"
    source.mkdir()
    (source / "a.txt").write_text("new-a\n", encoding="utf-8")
    dest_inode = dest.stat().st_ino
    hold = tmp_path / ".plugins-baked.hold"
    real_remove = safe_tree._remove_path

    def _fail_hold_reap(*, path: Path) -> None:
        """Fail only when removing the sibling hold directory.

        Args:
            path: Path being removed.

        Raises:
            OSError: When ``path`` is the hold directory.
        """
        if path.resolve() == hold.resolve():
            msg = "injected hold cleanup failure"
            raise OSError(msg)
        real_remove(path=path)

    monkeypatch.setattr(safe_tree, "_remove_path", _fail_hold_reap)
    with pytest.raises(OSError, match="injected hold cleanup failure"):
        install_directory(source=source, destination=dest)

    assert_that(dest.stat().st_ino).is_equal_to(dest_inode)
    assert_that((dest / "a.txt").read_text(encoding="utf-8")).is_equal_to(
        "new-a\n",
    )
    assert_that(hold.exists()).is_true()


def test_install_directory_preserves_inode_when_final_exchange_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed final exchange must not unlink the original cwd inode."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "a.txt").write_text("old-a\n", encoding="utf-8")
    source = tmp_path / "next"
    source.mkdir()
    (source / "a.txt").write_text("new-a\n", encoding="utf-8")
    dest_inode = dest.stat().st_ino
    real_exchange = safe_tree._exchange_paths
    calls = {"count": 0}

    def _fail_second_exchange(*, first: Path, second: Path) -> None:
        """Fail the closing exchange after a successful inode mirror.

        Args:
            first: First path.
            second: Second path.

        Raises:
            OSError: On the second exchange call.
        """
        calls["count"] += 1
        if calls["count"] == 2:
            msg = "injected exchange failure"
            raise OSError(msg)
        real_exchange(first=first, second=second)

    monkeypatch.setattr(safe_tree, "_exchange_paths", _fail_second_exchange)
    previous_cwd = Path.cwd()
    try:
        os.chdir(dest)
        with pytest.raises(OSError, match="injected exchange failure"):
            install_directory(source=source, destination=dest)
        Path("probe.txt").write_text("ok\n", encoding="utf-8")
        assert_that(Path.cwd().resolve()).is_equal_to(dest.resolve())
    finally:
        os.chdir(previous_cwd)

    assert_that(dest.stat().st_ino).is_equal_to(dest_inode)
    assert_that((dest / "a.txt").read_text(encoding="utf-8")).is_equal_to(
        "old-a\n",
    )
    assert_that((dest / "probe.txt").read_text(encoding="utf-8")).is_equal_to(
        "ok\n",
    )
    assert_that((tmp_path / ".plugins-baked.hold").exists()).is_false()


def test_install_directory_preserves_destination_inode_for_resident_cwd(
    tmp_path: Path,
) -> None:
    """A process cwd'd into plugins-baked keeps a valid working directory."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "old.txt").write_text("old\n", encoding="utf-8")
    source = tmp_path / "next"
    source.mkdir()
    (source / "new.txt").write_text("new\n", encoding="utf-8")
    dest_inode = dest.stat().st_ino
    previous_cwd = Path.cwd()
    try:
        os.chdir(dest)
        install_directory(source=source, destination=dest)
        Path("probe.txt").write_text("ok\n", encoding="utf-8")
        assert_that(Path.cwd().resolve()).is_equal_to(dest.resolve())
    finally:
        os.chdir(previous_cwd)

    assert_that(dest.stat().st_ino).is_equal_to(dest_inode)
    assert_that((dest / "new.txt").is_file()).is_true()
    assert_that((dest / "old.txt").exists()).is_false()
    assert_that((dest / "probe.txt").read_text(encoding="utf-8")).is_equal_to(
        "ok\n",
    )


def test_install_directory_replaces_dangling_destination_child_symlink(
    tmp_path: Path,
) -> None:
    """A dangling dest child symlink must not be followed while mirroring."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    outside = tmp_path / "outside-target"
    (dest / "COVERAGE.md").symlink_to(outside)
    source = tmp_path / "next"
    source.mkdir()
    (source / "COVERAGE.md").write_text("new\n", encoding="utf-8")

    install_directory(source=source, destination=dest)

    coverage = dest / "COVERAGE.md"
    assert_that(coverage.is_symlink()).is_false()
    assert_that(coverage.read_text(encoding="utf-8")).is_equal_to("new\n")
    assert_that(outside.exists()).is_false()


def test_install_directory_rejects_leftover_backup(
    tmp_path: Path,
) -> None:
    """A leftover backup directory must not be overwritten silently."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "COVERAGE.md").write_text("old\n", encoding="utf-8")
    (tmp_path / ".plugins-baked.bak").mkdir()
    source = tmp_path / "next"
    source.mkdir()
    (source / "COVERAGE.md").write_text("new\n", encoding="utf-8")

    with pytest.raises(ValueError, match="leftover bake backup"):
        install_directory(source=source, destination=dest)

    assert_that((dest / "COVERAGE.md").read_text(encoding="utf-8")).is_equal_to(
        "old\n",
    )


def test_install_directory_rejects_leftover_backup_when_destination_missing(
    tmp_path: Path,
) -> None:
    """A leftover backup still fails closed when dest has not been created."""
    dest = tmp_path / "plugins-baked"
    (tmp_path / ".plugins-baked.bak").mkdir()
    source = tmp_path / "next"
    source.mkdir()
    (source / "COVERAGE.md").write_text("new\n", encoding="utf-8")

    with pytest.raises(ValueError, match="leftover bake backup"):
        install_directory(source=source, destination=dest)

    assert_that(dest.exists()).is_false()


def test_install_directory_rejects_dangling_backup_when_destination_missing(
    tmp_path: Path,
) -> None:
    """A dangling leftover backup symlink fails closed when dest is absent."""
    dest = tmp_path / "plugins-baked"
    (tmp_path / ".plugins-baked.bak").symlink_to(tmp_path / "missing-backup")
    source = tmp_path / "next"
    source.mkdir()
    (source / "COVERAGE.md").write_text("new\n", encoding="utf-8")

    with pytest.raises(ValueError, match="leftover bake backup"):
        install_directory(source=source, destination=dest)

    assert_that(dest.exists()).is_false()


def test_install_directory_rejects_dangling_backup_symlink(
    tmp_path: Path,
) -> None:
    """A dangling leftover backup symlink must not be skipped by exists()."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "COVERAGE.md").write_text("old\n", encoding="utf-8")
    (tmp_path / ".plugins-baked.bak").symlink_to(tmp_path / "missing-backup")
    source = tmp_path / "next"
    source.mkdir()
    (source / "COVERAGE.md").write_text("new\n", encoding="utf-8")

    with pytest.raises(ValueError, match="leftover bake backup"):
        install_directory(source=source, destination=dest)

    assert_that((dest / "COVERAGE.md").read_text(encoding="utf-8")).is_equal_to(
        "old\n",
    )


def test_install_directory_rejects_leftover_hold(
    tmp_path: Path,
) -> None:
    """A leftover hold directory must not be overwritten silently."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "COVERAGE.md").write_text("old\n", encoding="utf-8")
    (tmp_path / ".plugins-baked.hold").mkdir()
    source = tmp_path / "next"
    source.mkdir()
    (source / "COVERAGE.md").write_text("new\n", encoding="utf-8")

    with pytest.raises(ValueError, match="leftover bake hold"):
        install_directory(source=source, destination=dest)

    assert_that((dest / "COVERAGE.md").read_text(encoding="utf-8")).is_equal_to(
        "old\n",
    )


def test_install_directory_rejects_leftover_hold_when_destination_missing(
    tmp_path: Path,
) -> None:
    """A leftover hold still fails closed when dest has not been created."""
    dest = tmp_path / "plugins-baked"
    (tmp_path / ".plugins-baked.hold").mkdir()
    source = tmp_path / "next"
    source.mkdir()
    (source / "COVERAGE.md").write_text("new\n", encoding="utf-8")

    with pytest.raises(ValueError, match="leftover bake hold"):
        install_directory(source=source, destination=dest)

    assert_that(dest.exists()).is_false()


def test_install_directory_rejects_symlink_planted_before_exclusive_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dest child symlink planted after unlink must not be followed."""
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "COVERAGE.md").write_text("old\n", encoding="utf-8")
    outside = tmp_path / "outside-target"
    source = tmp_path / "next"
    source.mkdir()
    (source / "COVERAGE.md").write_text("new\n", encoding="utf-8")
    dest_inode = dest.stat().st_ino
    real_create = safe_tree._create_exclusive_copy_at
    real_mirror = safe_tree._mirror_tree

    def _plant(
        *,
        source_fd: int,
        dir_fd: int,
        name: str,
        mode: int,
    ) -> None:
        """Plant a dangling symlink, then attempt the exclusive create.

        Args:
            source_fd: Open read fd for the source file.
            dir_fd: Open directory fd for the destination parent.
            name: Child name to create.
            mode: POSIX permission bits.

        Raises:
            OSError: When exclusive create refuses the planted symlink.
        """
        os.symlink(str(outside), name, dir_fd=dir_fd)
        real_create(
            source_fd=source_fd,
            dir_fd=dir_fd,
            name=name,
            mode=mode,
        )

    def _mirror_with_toctou(*, source: Path, destination: Path) -> None:
        """Install the TOCTOU plant only while mirroring onto the inode.

        Args:
            source: Staged tree now at the live path.
            destination: Original destination inode.
        """
        monkeypatch.setattr(
            safe_tree,
            "_create_exclusive_copy_at",
            _plant,
        )
        try:
            real_mirror(source=source, destination=destination)
        finally:
            monkeypatch.setattr(
                safe_tree,
                "_create_exclusive_copy_at",
                real_create,
            )

    monkeypatch.setattr(safe_tree, "_mirror_tree", _mirror_with_toctou)

    with pytest.raises(OSError):
        install_directory(source=source, destination=dest)

    assert_that(outside.exists()).is_false()
    assert_that(dest.stat().st_ino).is_equal_to(dest_inode)
    assert_that((dest / "COVERAGE.md").is_symlink()).is_false()
    assert_that((dest / "COVERAGE.md").read_text(encoding="utf-8")).is_equal_to(
        "old\n",
    )
    assert_that((tmp_path / ".plugins-baked.hold").exists()).is_false()


def test_install_directory_retries_partial_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A short os.write must be retried until the full payload is stored."""
    payload = "abcdefghijklmnop"
    dest = tmp_path / "plugins-baked"
    dest.mkdir()
    (dest / "payload.txt").write_text("old\n", encoding="utf-8")
    source = tmp_path / "next"
    source.mkdir()
    (source / "payload.txt").write_text(payload, encoding="utf-8")
    real_write = os.write

    def _partial_write(fd: int, data: bytes | bytearray | memoryview) -> int:
        """Write at most eight bytes per call.

        Args:
            fd: Destination file descriptor.
            data: Buffer passed to ``os.write``.

        Returns:
            Number of bytes written.
        """
        buffer = bytes(data)
        if len(buffer) > 8:
            return real_write(fd, buffer[:8])
        return real_write(fd, buffer)

    monkeypatch.setattr(safe_tree.os, "write", _partial_write)
    install_directory(source=source, destination=dest)
    assert_that((dest / "payload.txt").read_text(encoding="utf-8")).is_equal_to(
        payload,
    )


def test_write_all_rejects_zero_length_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write that returns zero before the buffer is exhausted fails closed."""

    def _zero_write(fd: int, data: bytes | bytearray | memoryview) -> int:
        """Pretend the descriptor accepted no bytes.

        Args:
            fd: Destination file descriptor.
            data: Buffer passed to ``os.write``.

        Returns:
            Always ``0``.
        """
        del fd, data
        return 0

    monkeypatch.setattr(safe_tree.os, "write", _zero_write)
    with pytest.raises(OSError, match="short write"):
        safe_tree._write_all(fd=1, data=b"hello")


def test_bake_preserves_plugins_baked_cwd(
    tmp_path: Path,
) -> None:
    """A full bake while cwd is plugins-baked must not invalidate getcwd."""
    _write_registry(repo_root=tmp_path, plugins_yaml="")
    bake_vendor_plugins.bake(repo_root=tmp_path)
    dest = tmp_path / "plugins-baked"
    dest_inode = dest.stat().st_ino
    previous_cwd = Path.cwd()
    try:
        os.chdir(dest)
        bake_vendor_plugins.bake(repo_root=tmp_path)
        Path("probe.txt").write_text("ok\n", encoding="utf-8")
        assert_that(Path.cwd().resolve()).is_equal_to(dest.resolve())
    finally:
        os.chdir(previous_cwd)

    assert_that(dest.stat().st_ino).is_equal_to(dest_inode)
    assert_that((dest / "probe.txt").read_text(encoding="utf-8")).is_equal_to(
        "ok\n",
    )


def test_bake_restores_plugins_baked_cwd_on_mirror_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed inode mirror during bake must leave resident cwd valid."""
    _write_registry(repo_root=tmp_path, plugins_yaml="")
    bake_vendor_plugins.bake(repo_root=tmp_path)
    dest = tmp_path / "plugins-baked"
    dest_inode = dest.stat().st_ino
    coverage_before = (dest / "COVERAGE.md").read_text(encoding="utf-8")

    def _fail_mirror(*, source: Path, destination: Path) -> None:
        """Inject a failure after the destination path already holds the new tree.

        Args:
            source: Staged tree now at the live path.
            destination: Original destination inode.

        Raises:
            OSError: Always.
        """
        del source, destination
        msg = "injected mirror failure"
        raise OSError(msg)

    monkeypatch.setattr(safe_tree, "_mirror_tree", _fail_mirror)
    previous_cwd = Path.cwd()
    try:
        os.chdir(dest)
        with pytest.raises(OSError, match="injected mirror failure"):
            bake_vendor_plugins.bake(repo_root=tmp_path)
        Path("probe.txt").write_text("ok\n", encoding="utf-8")
        assert_that(Path.cwd().resolve()).is_equal_to(dest.resolve())
    finally:
        os.chdir(previous_cwd)

    assert_that(dest.stat().st_ino).is_equal_to(dest_inode)
    assert_that((dest / "COVERAGE.md").read_text(encoding="utf-8")).is_equal_to(
        coverage_before,
    )
    assert_that((dest / "probe.txt").read_text(encoding="utf-8")).is_equal_to(
        "ok\n",
    )
    assert_that((tmp_path / ".plugins-baked.hold").exists()).is_false()


def test_bake_restores_complete_tree_on_partial_mirror_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial inode mirror during bake must restore the complete old tree."""
    _write_registry(repo_root=tmp_path, plugins_yaml="")
    bake_vendor_plugins.bake(repo_root=tmp_path)
    dest = tmp_path / "plugins-baked"
    dest_inode = dest.stat().st_ino
    coverage_before = (dest / "COVERAGE.md").read_text(encoding="utf-8")
    marketplace_before = (dest / ".claude-plugin" / "marketplace.json").read_text(
        encoding="utf-8",
    )

    def _partial_mirror(*, source: Path, destination: Path) -> None:
        """Copy one real file onto the original inode, then fail.

        Args:
            source: Staged tree now at the live path.
            destination: Original destination inode.

        Raises:
            OSError: After the first file copy.
        """
        first = min(
            (path for path in source.iterdir() if path.is_file()),
            key=lambda path: path.name,
        )
        safe_tree._copy_file_nofollow(
            source=first,
            destination=destination / first.name,
        )
        msg = "injected partial mirror failure"
        raise OSError(msg)

    monkeypatch.setattr(safe_tree, "_mirror_tree", _partial_mirror)
    previous_cwd = Path.cwd()
    try:
        os.chdir(dest)
        with pytest.raises(OSError, match="injected partial mirror failure"):
            bake_vendor_plugins.bake(repo_root=tmp_path)
        Path("probe.txt").write_text("ok\n", encoding="utf-8")
        assert_that(Path.cwd().resolve()).is_equal_to(dest.resolve())
    finally:
        os.chdir(previous_cwd)

    assert_that(dest.stat().st_ino).is_equal_to(dest_inode)
    assert_that((dest / "COVERAGE.md").read_text(encoding="utf-8")).is_equal_to(
        coverage_before,
    )
    assert_that(
        (dest / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"),
    ).is_equal_to(marketplace_before)
    assert_that((dest / "probe.txt").read_text(encoding="utf-8")).is_equal_to(
        "ok\n",
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


def test_check_rejects_leftover_hold(
    tmp_path: Path,
) -> None:
    """Offline --check must fail closed when a bake hold sidecar remains."""
    _write_registry(repo_root=tmp_path, plugins_yaml="")
    bake_vendor_plugins.bake(repo_root=tmp_path)
    (tmp_path / ".plugins-baked.hold").mkdir()
    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


def test_check_rejects_leftover_backup(
    tmp_path: Path,
) -> None:
    """Offline --check must fail closed when a bake backup sidecar remains."""
    _write_registry(repo_root=tmp_path, plugins_yaml="")
    bake_vendor_plugins.bake(repo_root=tmp_path)
    (tmp_path / ".plugins-baked.bak").mkdir()
    assert_that(bake_vendor_plugins.check(repo_root=tmp_path)).is_equal_to(1)


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
