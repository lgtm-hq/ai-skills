"""Tests for vendor registry validation and baked-index filtering."""

from __future__ import annotations

import json
from pathlib import Path

import bake_vendor_indexes
import pytest
from assertpy import assert_that
from vendor_registry.registry import (
    discover_skills,
    load_registry,
    render_index,
    render_notice,
    validate_index,
)
from vendor_registry.vendor import Vendor

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "vendor_registry"


def _replace_once(*, contents: str, source: str, replacement: str) -> str:
    """Replace exactly one occurrence or fail the test.

    Args:
        contents: Original fixture text.
        source: Substring that must appear exactly once.
        replacement: Replacement text.

    Returns:
        Updated fixture text.

    Raises:
        AssertionError: If ``source`` is missing or appears more than once.
    """
    count = contents.count(source)
    assert_that(count).is_equal_to(1)
    return contents.replace(source, replacement, 1)


@pytest.fixture
def valid_registry_path(tmp_path: Path) -> Path:
    """Copy the valid registry fixture into an isolated repository root.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        Path to the copied ``vendors.yaml`` fixture.
    """
    registry_path = tmp_path / "vendors.yaml"
    registry_path.write_text(
        FIXTURES_DIR.joinpath("valid-vendors.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    tmp_path.joinpath("bundles.yaml").write_text(
        """---
groups:
  git-pr:
    id: git-pr
    name: Git & PR Workflow
    description: First-party plugin.
    skills:
      - branch
""",
        encoding="utf-8",
    )
    return registry_path


def test_load_registry_accepts_valid_vendor(
    valid_registry_path: Path,
) -> None:
    """Accept a complete registry with forward-compatible glob roots."""
    vendors = load_registry(registry_path=valid_registry_path)

    assert_that(vendors).is_length(1)
    assert_that(vendors[0]).is_equal_to(
        Vendor(
            id="example-vendor",
            repo="owner/repository",
            sha="0123456789abcdef0123456789abcdef01234567",
            skill_roots=("plugins/*/skills", "skills"),
            license="MIT",
            homepage="https://example.com/repository",
        ),
    )


@pytest.mark.parametrize(
    ("source", "replacement", "message"),
    [
        pytest.param(
            "- id: example-vendor",
            "- id: Example",
            "id must be a lowercase slug",
            id="invalid-id",
        ),
        pytest.param(
            'sha: "0123456789abcdef0123456789abcdef01234567"',
            'sha: "short"',
            "sha must be a 40-character",
            id="invalid-sha",
        ),
        pytest.param(
            "skillRoots:\n      - plugins/*/skills\n      - skills",
            "skillRoots: []",
            "skillRoots must be a non-empty list",
            id="empty-roots",
        ),
        pytest.param(
            "skillRoots:\n      - plugins/*/skills\n      - skills",
            "skillRoots:\n      - /skills",
            "skillRoots entries must be relative",
            id="absolute-root",
        ),
        pytest.param(
            "skillRoots:\n      - plugins/*/skills\n      - skills",
            "skillRoots:\n      - skills/",
            "skillRoots entries must be relative",
            id="trailing-slash-root",
        ),
        pytest.param(
            "skillRoots:\n      - plugins/*/skills\n      - skills",
            "skillRoots:\n      - skills/./nested",
            "skillRoots entries must be relative",
            id="dot-component-root",
        ),
        pytest.param(
            "skillRoots:\n      - plugins/*/skills\n      - skills",
            'skillRoots:\n      - " skills"',
            "skillRoots entries must be relative",
            id="whitespace-root",
        ),
        pytest.param(
            "homepage: https://example.com/repository",
            "homepage: ftp://example.com",
            r"homepage must be an http\(s\) URL",
            id="invalid-homepage",
        ),
    ],
)
def test_load_registry_rejects_invalid_required_fields(
    valid_registry_path: Path,
    source: str,
    replacement: str,
    message: str,
) -> None:
    """Fail closed when an individual vendor field violates schema."""
    registry_path = valid_registry_path
    contents = registry_path.read_text(encoding="utf-8")
    registry_path.write_text(
        contents.replace(source, replacement),
        encoding="utf-8",
    )

    with pytest.raises((TypeError, ValueError), match=message):
        load_registry(registry_path=registry_path)


def test_load_registry_accepts_optional_display_ref(
    valid_registry_path: Path,
) -> None:
    """Allow consumer-facing displayRef pins that are not commit SHAs."""
    registry_path = valid_registry_path
    contents = registry_path.read_text(encoding="utf-8")
    registry_path.write_text(
        _replace_once(
            contents=contents,
            source="homepage: https://example.com/repository",
            replacement="displayRef: latest\n    homepage: https://example.com/repository",
        ),
        encoding="utf-8",
    )

    vendors = load_registry(registry_path=registry_path)

    assert_that(vendors).is_length(1)
    assert_that(vendors[0].id).is_equal_to("example-vendor")
    assert_that(vendors[0].display_ref).is_equal_to("latest")


def test_load_registry_rejects_sha_display_ref(
    valid_registry_path: Path,
) -> None:
    """Reject displayRef values that look like commit SHAs."""
    registry_path = valid_registry_path
    contents = registry_path.read_text(encoding="utf-8")
    registry_path.write_text(
        _replace_once(
            contents=contents,
            source="homepage: https://example.com/repository",
            replacement=(
                "displayRef: 0123456789abcdef0123456789abcdef01234567\n"
                "    homepage: https://example.com/repository"
            ),
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="displayRef must not be a commit SHA"):
        load_registry(registry_path=registry_path)


def test_load_registry_rejects_uppercase_sha_display_ref(
    valid_registry_path: Path,
) -> None:
    """Reject uppercase 40-char hex displayRef values as commit SHAs."""
    registry_path = valid_registry_path
    contents = registry_path.read_text(encoding="utf-8")
    registry_path.write_text(
        _replace_once(
            contents=contents,
            source="homepage: https://example.com/repository",
            replacement=(
                "displayRef: ABCDEF0123456789ABCDEF0123456789ABCDEF01\n"
                "    homepage: https://example.com/repository"
            ),
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="displayRef must not be a commit SHA"):
        load_registry(registry_path=registry_path)


def test_load_registry_rejects_padded_sha_display_ref(
    valid_registry_path: Path,
) -> None:
    """Reject whitespace-padded 40-char hex displayRef values as commit SHAs."""
    registry_path = valid_registry_path
    contents = registry_path.read_text(encoding="utf-8")
    registry_path.write_text(
        _replace_once(
            contents=contents,
            source="homepage: https://example.com/repository",
            replacement=(
                'displayRef: "  0123456789abcdef0123456789abcdef01234567  "\n'
                "    homepage: https://example.com/repository"
            ),
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="displayRef must not be a commit SHA"):
        load_registry(registry_path=registry_path)


def test_discover_skills_filters_descendants_of_glob_roots() -> None:
    """Include all skill files below configured roots, including nested ones."""
    skills = discover_skills(
        paths=[
            "plugins/one/skills/alpha/SKILL.md",
            "plugins/two/skills/beta/SKILL.md",
            "plugins/one/skills/alpha/examples/SKILL.md",
            "plugins/one/other/gamma/SKILL.md",
            "skills/root/SKILL.md",
        ],
        skill_roots=("plugins/*/skills", "skills"),
    )

    assert_that(skills).is_equal_to(
        [
            {"name": "alpha", "path": "plugins/one/skills/alpha"},
            {
                "name": "examples",
                "path": "plugins/one/skills/alpha/examples",
            },
            {"name": "beta", "path": "plugins/two/skills/beta"},
            {"name": "root", "path": "skills/root"},
        ],
    )


def test_discover_skills_rejects_cross_directory_glob_matches() -> None:
    """Exclude paths where a root wildcard would otherwise cross directories."""
    skills = discover_skills(
        paths=[
            "plugins/one/extra/skills/alpha/SKILL.md",
            "plugins/one/skills/alpha/SKILL.md",
        ],
        skill_roots=("plugins/*/skills",),
    )

    assert_that(skills).is_equal_to(
        [{"name": "alpha", "path": "plugins/one/skills/alpha"}],
    )


def test_validate_index_accepts_matching_metadata_and_skills(tmp_path: Path) -> None:
    """Accept a stable index that matches its registry vendor offline."""
    vendor = Vendor(
        id="example",
        repo="owner/repository",
        sha="0123456789abcdef0123456789abcdef01234567",
        skill_roots=("skills",),
        license="MIT",
        homepage="https://example.com/repository",
    )
    index_path = tmp_path / "example.json"
    index_path.write_text(
        render_index(
            vendor=vendor,
            skills=[{"name": "alpha", "path": "skills/alpha"}],
        ),
        encoding="utf-8",
    )

    validate_index(index_path=index_path, vendor=vendor)


def test_validate_index_rejects_metadata_drift(tmp_path: Path) -> None:
    """Reject an index baked from a SHA other than the registry pin."""
    vendor = Vendor(
        id="example",
        repo="owner/repository",
        sha="0123456789abcdef0123456789abcdef01234567",
        skill_roots=("skills",),
        license="MIT",
        homepage="https://example.com/repository",
    )
    index_path = tmp_path / "example.json"
    index_path.write_text(
        """{
  "vendor": {
    "id": "example",
    "repo": "owner/repository",
    "sha": "ffffffffffffffffffffffffffffffffffffffff",
    "skillRoots": ["skills"]
  },
  "skills": []
}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="metadata does not match"):
        validate_index(index_path=index_path, vendor=vendor)


def test_render_notice_records_anthropic_document_skill_nuance() -> None:
    """Document the confirmed Anthropic registry license qualification."""
    notice = render_notice(
        vendors=(
            Vendor(
                id="anthropics",
                repo="anthropics/skills",
                sha="0123456789abcdef0123456789abcdef01234567",
                skill_roots=("skills",),
                license="Apache-2.0",
                homepage="https://github.com/anthropics/skills",
            ),
        ),
    )

    assert_that(notice).contains("document skills are source-available")
    assert_that(notice).contains("Apache-2.0")


def test_render_notice_records_claude_code_commercial_terms() -> None:
    """Document Claude Code plugin skills under Anthropic commercial terms."""
    notice = render_notice(
        vendors=(
            Vendor(
                id="anthropics-claude-code",
                repo="anthropics/claude-code",
                sha="0123456789abcdef0123456789abcdef01234567",
                skill_roots=("plugins/*/skills",),
                license="Commercial",
                homepage="https://github.com/anthropics/claude-code",
            ),
        ),
    )

    assert_that(notice).contains("anthropics/claude-code")
    assert_that(notice).contains("Commercial")
    assert_that(notice).contains("Commercial Terms of Service")


def test_committed_claude_code_index_includes_frontend_design() -> None:
    """Baked claude-code indexes must expose plugin-buried frontend-design."""
    repo_root = Path(__file__).resolve().parents[1]
    index_paths = (
        repo_root / "vendor-indexes" / "anthropics-claude-code.json",
        repo_root
        / "npm"
        / "ai-skills"
        / "data"
        / "vendor-indexes"
        / "anthropics-claude-code.json",
    )
    for index_path in index_paths:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        skills = {skill["name"]: skill["path"] for skill in payload["skills"]}

        assert_that(payload["vendor"]["id"]).is_equal_to("anthropics-claude-code")
        assert_that(payload["vendor"]["skillRoots"]).is_equal_to(
            ["plugins/*/skills"],
        )
        assert_that(skills).contains_key("frontend-design")
        assert_that(skills["frontend-design"]).is_equal_to(
            "plugins/frontend-design/skills/frontend-design",
        )
    root_index = index_paths[0].read_text(encoding="utf-8")
    packaged_index = index_paths[1].read_text(encoding="utf-8")
    assert_that(packaged_index).is_equal_to(root_index)


def test_bake_preserves_committed_artifacts_when_fetch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not replace committed output when a later vendor fetch fails."""
    tmp_path.joinpath("vendors.yaml").write_text(
        """---
vendors:
  - id: first
    repo: owner/first
    sha: "0123456789abcdef0123456789abcdef01234567"
    skillRoots: ["skills"]
    license: MIT
    homepage: https://example.com/first
  - id: second
    repo: owner/second
    sha: "89abcdef0123456789abcdef0123456789abcdef"
    skillRoots: ["skills"]
    license: MIT
    homepage: https://example.com/second
""",
        encoding="utf-8",
    )
    indexes_dir = tmp_path / "vendor-indexes"
    indexes_dir.mkdir()
    first_index = indexes_dir / "first.json"
    first_index.write_text("existing index\n", encoding="utf-8")
    notice_path = tmp_path / "NOTICE.md"
    notice_path.write_text("existing notice\n", encoding="utf-8")

    def _fetch_then_fail(*, vendor: Vendor) -> list[str]:
        """Return a first tree then simulate a later network failure.

        Args:
            vendor: Vendor being fetched.

        Returns:
            Blob paths for the first vendor.

        Raises:
            RuntimeError: For the second vendor's simulated API failure.
        """
        if vendor.id == "first":
            return ["skills/alpha/SKILL.md"]
        msg = "network failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(bake_vendor_indexes, "_fetch_tree_paths", _fetch_then_fail)

    with pytest.raises(RuntimeError, match="network failure"):
        bake_vendor_indexes.bake(repo_root=tmp_path)

    assert_that(first_index.read_text(encoding="utf-8")).is_equal_to("existing index\n")
    assert_that(notice_path.read_text(encoding="utf-8")).is_equal_to(
        "existing notice\n"
    )


_PLUGIN_SLICE = """
    plugins:
      - id: example-plugin
        description: Example vendor plugin.
        skillsRoot: skills
        skills: "*"
        extraSkills:
          - extras/bonus
        extraFiles:
          - README.md
        renameSkills:
          teach: teach-example
        agents:
          - comment-sicko
          - code-reviewer
"""


def _with_plugins(*, registry_path: Path, plugins: str = _PLUGIN_SLICE) -> Path:
    """Append a plugin slice after the fixture homepage field.

    Args:
        registry_path: Isolated ``vendors.yaml`` path.
        plugins: YAML block to insert.

    Returns:
        The same ``registry_path``.
    """
    contents = registry_path.read_text(encoding="utf-8")
    registry_path.write_text(
        _replace_once(
            contents=contents,
            source="homepage: https://example.com/repository",
            replacement=f"homepage: https://example.com/repository{plugins}",
        ),
        encoding="utf-8",
    )
    return registry_path


def test_load_registry_accepts_plugin_slice(valid_registry_path: Path) -> None:
    """Accept a reviewed plugin slice with glob ingest and collision rename."""
    vendors = load_registry(
        registry_path=_with_plugins(registry_path=valid_registry_path),
    )

    assert_that(vendors).is_length(1)
    plugin = vendors[0].plugins[0]
    assert_that(plugin.id).is_equal_to("example-plugin")
    assert_that(plugin.description).is_equal_to("Example vendor plugin.")
    assert_that(plugin.skills_root).is_equal_to("skills")
    assert_that(plugin.skills).is_equal_to("*")
    assert_that(plugin.extra_skills).is_equal_to(("extras/bonus",))
    assert_that(plugin.extra_files).is_equal_to(("README.md",))
    assert_that(plugin.rename_skills).is_equal_to((("teach", "teach-example"),))
    assert_that(plugin.agents).is_equal_to(("comment-sicko", "code-reviewer"))


def test_load_registry_accepts_omitted_plugins(valid_registry_path: Path) -> None:
    """Keep omitted plugins valid as a schema-only declaration."""
    vendors = load_registry(registry_path=valid_registry_path)

    assert_that(vendors[0].plugins).is_equal_to(())


def test_committed_registry_declares_five_vendor_plugin_slices() -> None:
    """The five registered vendors declare collision-resolved plugin slices."""
    vendors = load_registry(
        registry_path=Path(__file__).resolve().parents[1] / "vendors.yaml",
    )
    plugins = [plugin.id for vendor in vendors for plugin in vendor.plugins]
    assert_that(plugins).is_equal_to(
        [
            "mattpocock-skills",
            "document-skills",
            "example-skills",
            "claude-api",
            "claude-opus-4-5-migration",
            "claude-code-frontend-design",
            "hookify",
            "plugin-dev",
            "caveman",
            "davidondrej-skills",
        ],
    )
    rename_targets = {
        new
        for vendor in vendors
        for plugin in vendor.plugins
        for _old, new in plugin.rename_skills
    }
    assert_that(rename_targets).contains(
        "frontend-design-claude-code",
        "teach-davidondrej",
        "handoff-davidondrej",
    )


def test_load_registry_accepts_empty_plugins_list(valid_registry_path: Path) -> None:
    """Allow an explicit empty plugins list as a schema-only declaration."""
    vendors = load_registry(
        registry_path=_with_plugins(
            registry_path=valid_registry_path,
            plugins="\n    plugins: []",
        ),
    )

    assert_that(vendors[0].plugins).is_equal_to(())


def test_load_registry_accepts_skill_path_list(valid_registry_path: Path) -> None:
    """Accept an explicit skill-path list relative to skillsRoot."""
    vendors = load_registry(
        registry_path=_with_plugins(
            registry_path=valid_registry_path,
            plugins="""
    plugins:
      - id: example-plugin
        description: Example vendor plugin.
        skillsRoot: skills
        skills:
          - alpha
          - nested/beta
""",
        ),
    )

    assert_that(vendors[0].plugins[0].skills).is_equal_to(("alpha", "nested/beta"))


@pytest.mark.parametrize(
    ("source", "replacement", "message"),
    [
        pytest.param(
            "id: example-plugin",
            "id: ExamplePlugin",
            "id must be a lowercase slug",
            id="invalid-plugin-id",
        ),
        pytest.param(
            'skills: "*"',
            "skills: []",
            r'skills must be "\*" or a non-empty list',
            id="empty-skills",
        ),
        pytest.param(
            'skills: "*"',
            "skills:\n          - extras/*.md",
            "skills entries must not contain glob metacharacters",
            id="glob-skills-list",
        ),
        pytest.param(
            'skills: "*"',
            "skills:\n          - alpha\n          - alpha",
            "skills paths must be unique",
            id="duplicate-skills-path",
        ),
        pytest.param(
            "description: Example vendor plugin.",
            'description: ""',
            "plugin example-plugin description must not be empty",
            id="empty-plugin-description",
        ),
        pytest.param(
            "skillsRoot: skills",
            "skillsRoot: skills\n        extra-field: nope",
            "must contain required fields",
            id="unknown-plugin-key",
        ),
        pytest.param(
            "extraSkills:\n          - extras/bonus",
            "extraSkills:\n          - /extras/bonus",
            "extraSkills entries must be relative",
            id="absolute-extra-skill",
        ),
        pytest.param(
            "extraFiles:\n          - README.md",
            "extraFiles:\n          - /README.md",
            "extraFiles entries must be relative",
            id="absolute-extra-file",
        ),
        pytest.param(
            "extraFiles:\n          - README.md",
            "extraFiles: []",
            "extraFiles must be a non-empty list",
            id="empty-extra-files",
        ),
        pytest.param(
            "extraFiles:\n          - README.md",
            "extraFiles:\n          - docs/README.md\n          - other/README.md",
            "extraFiles basenames must be unique",
            id="duplicate-extra-file-basename",
        ),
        pytest.param(
            "extraFiles:\n          - README.md",
            "extraFiles:\n          - vendor/skills",
            "extraFiles basename 'skills' is reserved",
            id="reserved-extra-file-basename",
        ),
        pytest.param(
            "teach: teach-example",
            "teach: teach",
            "renameSkills must change the skill name",
            id="identity-rename",
        ),
        pytest.param(
            "teach: teach-example",
            "Teach: teach-example",
            "renameSkills keys and values must be lowercase slugs",
            id="rename-not-slug",
        ),
        pytest.param(
            "teach: teach-example",
            '" teach ": teach-example',
            "renameSkills keys and values must be lowercase slugs",
            id="padded-rename",
        ),
        pytest.param(
            "- comment-sicko\n          - code-reviewer",
            "- CommentSicko",
            "agents entries must be lowercase slugs",
            id="invalid-agent-slug",
        ),
        pytest.param(
            "agents:\n          - comment-sicko\n          - code-reviewer",
            "agents: []",
            "agents must be a non-empty list",
            id="empty-agents",
        ),
        pytest.param(
            "agents:\n          - comment-sicko\n          - code-reviewer",
            "agents: null",
            "agents must be a list",
            id="null-agents",
        ),
        pytest.param(
            "extraSkills:\n          - extras/bonus",
            "extraSkills: null",
            "extraSkills must be a list",
            id="null-extra-skills",
        ),
        pytest.param(
            "renameSkills:\n          teach: teach-example",
            "renameSkills: null",
            "renameSkills must be a mapping",
            id="null-rename-skills",
        ),
        pytest.param(
            "extraSkills:\n          - extras/bonus",
            'extraSkills:\n          - " ../escape "',
            "extraSkills entries must be relative",
            id="whitespace-dotdot-extra",
        ),
        pytest.param(
            "extraSkills:\n          - extras/bonus",
            'extraSkills:\n          - "extras\\\\bonus"',
            "extraSkills entries must be relative",
            id="backslash-extra",
        ),
        pytest.param(
            "extraSkills:\n          - extras/bonus",
            "extraSkills:\n          - extras/./bonus",
            "extraSkills entries must be relative",
            id="dot-component-extra",
        ),
        pytest.param(
            "extraSkills:\n          - extras/bonus",
            "extraSkills:\n          - extras/../bonus",
            "extraSkills entries must be relative",
            id="dotdot-component-extra",
        ),
        pytest.param(
            "extraSkills:\n          - extras/bonus",
            "extraSkills:\n          - extras/*.md",
            "extraSkills entries must not contain glob metacharacters",
            id="glob-extra",
        ),
        pytest.param(
            "extraSkills:\n          - extras/bonus",
            "extraSkills:\n          - extras/bonus\n          - extras/bonus",
            "extraSkills entries must be unique",
            id="duplicate-extra",
        ),
        pytest.param(
            "- comment-sicko\n          - code-reviewer",
            "- comment-sicko\n          - comment-sicko",
            "agents entries must be unique",
            id="duplicate-agents",
        ),
        pytest.param(
            "extraSkills:\n          - extras/bonus",
            'extraSkills:\n          - "bad\\0path"',
            "extraSkills entries must be relative",
            id="nul-extra",
        ),
        pytest.param(
            'skills: "*"',
            "skills:\n          - '*'",
            r'skills list must not contain "\*"',
            id="star-in-skills-list",
        ),
        pytest.param(
            "description: Example vendor plugin.",
            "description: |\n          Example vendor plugin.",
            "must not contain control characters",
            id="multiline-description",
        ),
    ],
)
def test_load_registry_rejects_invalid_plugin_fields(
    valid_registry_path: Path,
    source: str,
    replacement: str,
    message: str,
) -> None:
    """Fail closed when a plugin slice violates the reviewed schema."""
    registry_path = _with_plugins(registry_path=valid_registry_path)
    contents = registry_path.read_text(encoding="utf-8")
    registry_path.write_text(
        _replace_once(contents=contents, source=source, replacement=replacement),
        encoding="utf-8",
    )

    with pytest.raises((TypeError, ValueError), match=message):
        load_registry(registry_path=registry_path)


def test_load_registry_rejects_duplicate_plugin_ids(
    valid_registry_path: Path,
) -> None:
    """Reject two slices on one vendor that share a plugin id."""
    _with_plugins(
        registry_path=valid_registry_path,
        plugins="""
    plugins:
      - id: example-plugin
        description: First slice.
        skillsRoot: skills
        skills: "*"
      - id: example-plugin
        description: Duplicate slice.
        skillsRoot: skills
        skills: "*"
""",
    )

    with pytest.raises(ValueError, match="plugin ids must be unique"):
        load_registry(registry_path=valid_registry_path)


def test_load_registry_rejects_cross_vendor_plugin_id_collision(
    tmp_path: Path,
) -> None:
    """Reject the same plugin id declared by two vendors."""
    registry_path = tmp_path / "vendors.yaml"
    registry_path.write_text(
        """---
vendors:
  - id: first-vendor
    repo: owner/first
    sha: "0123456789abcdef0123456789abcdef01234567"
    skillRoots:
      - skills
    license: MIT
    homepage: https://example.com/first
    plugins:
      - id: shared-plugin
        description: First vendor slice.
        skillsRoot: skills
        skills: "*"
  - id: second-vendor
    repo: owner/second
    sha: "89abcdef0123456789abcdef0123456789abcdef"
    skillRoots:
      - skills
    license: MIT
    homepage: https://example.com/second
    plugins:
      - id: shared-plugin
        description: Second vendor slice.
        skillsRoot: skills
        skills: "*"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be unique across vendors"):
        load_registry(registry_path=registry_path)


def test_load_registry_rejects_first_party_plugin_id_collision(
    valid_registry_path: Path,
) -> None:
    """Reject a vendor plugin id that matches a bundles.yaml group id."""
    valid_registry_path.parent.joinpath("bundles.yaml").write_text(
        """---
groups:
  git-pr:
    id: git-pr
    name: Git & PR Workflow
    description: First-party plugin.
    skills:
      - branch
""",
        encoding="utf-8",
    )
    _with_plugins(
        registry_path=valid_registry_path,
        plugins="""
    plugins:
      - id: git-pr
        description: Collides with first-party plugin.
        skillsRoot: skills
        skills: "*"
""",
    )

    with pytest.raises(ValueError, match="collides with a first-party plugin id"):
        load_registry(registry_path=valid_registry_path)


def test_load_registry_rejects_duplicate_rename_targets_across_plugins(
    valid_registry_path: Path,
) -> None:
    """Reject two plugins renaming different skills onto the same explode name."""
    _with_plugins(
        registry_path=valid_registry_path,
        plugins="""
    plugins:
      - id: first-plugin
        description: First slice.
        skillsRoot: skills
        skills: "*"
        renameSkills:
          teach: shared-name
      - id: second-plugin
        description: Second slice.
        skillsRoot: extras
        skills: "*"
        renameSkills:
          handoff: shared-name
""",
    )

    with pytest.raises(ValueError, match="renameSkills targets must be unique"):
        load_registry(registry_path=valid_registry_path)


def test_load_registry_rejects_null_plugins(valid_registry_path: Path) -> None:
    """Reject ``plugins: null``; omit the key or use an empty list instead."""
    _with_plugins(
        registry_path=valid_registry_path,
        plugins="\n    plugins: null",
    )

    with pytest.raises(TypeError, match="plugins must be a list"):
        load_registry(registry_path=valid_registry_path)


def test_load_registry_rejects_duplicate_yaml_keys(
    valid_registry_path: Path,
) -> None:
    """Fail closed when YAML last-wins would drop a colliding mapping key."""
    _with_plugins(
        registry_path=valid_registry_path,
        plugins="""
    plugins:
      - id: example-plugin
        description: Example vendor plugin.
        skillsRoot: skills
        skills: "*"
        renameSkills:
          teach: teach-example
          teach: teach-other
""",
    )

    with pytest.raises(ValueError, match="duplicate key"):
        load_registry(registry_path=valid_registry_path)


def test_load_registry_rejects_malformed_first_party_group(
    valid_registry_path: Path,
) -> None:
    """Fail closed when bundles.yaml groups are not mappings."""
    valid_registry_path.parent.joinpath("bundles.yaml").write_text(
        """---
groups:
  broken: not-a-mapping
""",
        encoding="utf-8",
    )
    _with_plugins(registry_path=valid_registry_path)

    with pytest.raises(TypeError, match="must be a mapping"):
        load_registry(registry_path=valid_registry_path)


def test_load_registry_rejects_first_party_group_without_id(
    valid_registry_path: Path,
) -> None:
    """Fail closed when a bundles.yaml group is missing its plugin id."""
    valid_registry_path.parent.joinpath("bundles.yaml").write_text(
        """---
groups:
  broken:
    name: Missing id
""",
        encoding="utf-8",
    )
    _with_plugins(registry_path=valid_registry_path)

    with pytest.raises(ValueError, match="must have a non-empty string id"):
        load_registry(registry_path=valid_registry_path)


def test_load_registry_rejects_cross_vendor_rename_target_collision(
    tmp_path: Path,
) -> None:
    """Reject two vendors renaming different skills onto the same explode name."""
    registry_path = tmp_path / "vendors.yaml"
    registry_path.write_text(
        """---
vendors:
  - id: first-vendor
    repo: owner/first
    sha: "0123456789abcdef0123456789abcdef01234567"
    skillRoots:
      - skills
    license: MIT
    homepage: https://example.com/first
    plugins:
      - id: first-plugin
        description: First vendor slice.
        skillsRoot: skills
        skills: "*"
        renameSkills:
          teach: shared-explode
  - id: second-vendor
    repo: owner/second
    sha: "89abcdef0123456789abcdef0123456789abcdef"
    skillRoots:
      - skills
    license: MIT
    homepage: https://example.com/second
    plugins:
      - id: second-plugin
        description: Second vendor slice.
        skillsRoot: skills
        skills: "*"
        renameSkills:
          handoff: shared-explode
""",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="renameSkills targets must be unique across vendors",
    ):
        load_registry(registry_path=registry_path)
