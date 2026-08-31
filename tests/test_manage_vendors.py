"""Tests for the vendor management CLI."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import bake_vendor_indexes
import bake_vendor_plugins
import manage_vendors
import pytest
import yaml
from assertpy import assert_that
from vendor_registry.registry import load_registry
from vendor_registry.vendor import Vendor

_EXISTING_SHA = "0123456789abcdef0123456789abcdef01234567"
_NEW_SHA = "89abcdef0123456789abcdef0123456789abcdef"
_FETCHED_TREE = ["skills/alpha/SKILL.md", "skills/beta/SKILL.md"]


def _fake_tree(*, vendor: Vendor) -> list[str]:
    """Return a fixed skill tree, ignoring the requested vendor.

    Args:
        vendor: Vendor whose tree would normally be fetched.

    Returns:
        A stable list of ``SKILL.md`` blob paths.
    """
    del vendor
    return list(_FETCHED_TREE)


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


def _fake_vendor_plugin_tree(*, vendor: Vendor, dest: Path) -> None:
    """Populate a local vendor tree used when plugin slices are baked.

    Args:
        vendor: Vendor whose archive would normally be fetched.
        dest: Directory that receives the unpacked tree.
    """
    del vendor
    dest.mkdir(parents=True, exist_ok=True)
    _write_skill(directory=dest / "skills" / "alpha", name="alpha")
    _write_skill(directory=dest / "skills" / "gamma", name="gamma")
    _write_skill(directory=dest / "skills" / "teach", name="teach")
    _write_skill(directory=dest / "skills" / "nested" / "beta", name="beta")
    _write_skill(directory=dest / "extras" / "bonus", name="bonus")
    agents = dest / "agents"
    agents.mkdir()
    agents.joinpath("comment-sicko.md").write_text(
        "# comment-sicko\n",
        encoding="utf-8",
    )


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build an isolated repository root with baked, synchronized artifacts.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Fixture used to stub the GitHub tree fetch.

    Returns:
        Path to a repository root ready for management commands.
    """
    monkeypatch.setattr(bake_vendor_indexes, "_fetch_tree_paths", _fake_tree)
    monkeypatch.setattr(
        bake_vendor_plugins,
        "_fetch_vendor_tree",
        _fake_vendor_plugin_tree,
    )
    tmp_path.joinpath("vendors.yaml").write_text(
        "---\n"
        "vendors:\n"
        "  - id: existing\n"
        "    repo: owner/existing\n"
        f'    sha: "{_EXISTING_SHA}"\n'
        "    displayRef: latest\n"
        "    skillRoots:\n"
        "      - skills\n"
        "    license: MIT\n"
        "    homepage: https://github.com/owner/existing\n",
        encoding="utf-8",
    )
    tmp_path.joinpath("bundles.yaml").write_text(
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
    package_root = tmp_path / "npm" / "ai-skills"
    package_root.mkdir(parents=True)
    package_root.joinpath("package.json").write_text(
        '{\n  "name": "@lgtm-hq/ai-skills",\n  "version": "0.0.0-dev"\n}\n',
        encoding="utf-8",
    )
    manage_vendors.refresh(repo_root=tmp_path)
    return tmp_path


def test_add_appends_vendor_and_refreshes(repo_root: Path) -> None:
    """Add a vendor, persist it, and bake a matching index."""
    manage_vendors.add(
        repo_root=repo_root,
        vendor_id="brand-new",
        repo="owner/brand-new",
        sha=_NEW_SHA,
        skill_roots=("skills",),
        license_name="Apache-2.0",
        homepage="https://github.com/owner/brand-new",
        display_ref=None,
    )

    vendors = load_registry(registry_path=repo_root / "vendors.yaml")
    added = next(vendor for vendor in vendors if vendor.id == "brand-new")
    assert_that(added.repo).is_equal_to("owner/brand-new")
    assert_that(added.sha).is_equal_to(_NEW_SHA)
    index = json.loads(
        (repo_root / "vendor-indexes" / "brand-new.json").read_text(encoding="utf-8"),
    )
    assert_that(index["vendor"]["sha"]).is_equal_to(_NEW_SHA)
    assert_that({skill["name"] for skill in index["skills"]}).is_equal_to(
        {"alpha", "beta"},
    )
    assert_that(manage_vendors.check(repo_root=repo_root)).is_zero()


def test_add_defaults_display_ref_to_latest(repo_root: Path) -> None:
    """Default the consumer-facing display ref to ``latest`` on add."""
    manage_vendors.add(
        repo_root=repo_root,
        vendor_id="brand-new",
        repo="owner/brand-new",
        sha=_NEW_SHA,
        skill_roots=("skills",),
        license_name="MIT",
        homepage="https://github.com/owner/brand-new",
        display_ref=None,
    )

    registry_text = (repo_root / "vendors.yaml").read_text(encoding="utf-8")
    assert_that(registry_text).contains("displayRef: latest")


def test_add_rejects_duplicate_id(repo_root: Path) -> None:
    """Refuse to add a vendor whose id already exists."""
    with pytest.raises(ValueError, match="already exists"):
        manage_vendors.add(
            repo_root=repo_root,
            vendor_id="existing",
            repo="owner/existing",
            sha=_NEW_SHA,
            skill_roots=("skills",),
            license_name="MIT",
            homepage="https://github.com/owner/existing",
            display_ref=None,
        )


def test_update_patches_sha_and_rebakes(repo_root: Path) -> None:
    """Patch an existing vendor's SHA and rebake its index."""
    manage_vendors.update(
        repo_root=repo_root,
        vendor_id="existing",
        repo=None,
        sha=_NEW_SHA,
        skill_roots=None,
        license_name=None,
        homepage=None,
        display_ref=None,
    )

    vendors = load_registry(registry_path=repo_root / "vendors.yaml")
    updated = next(vendor for vendor in vendors if vendor.id == "existing")
    assert_that(updated.sha).is_equal_to(_NEW_SHA)
    assert_that(updated.repo).is_equal_to("owner/existing")
    index = json.loads(
        (repo_root / "vendor-indexes" / "existing.json").read_text(encoding="utf-8"),
    )
    assert_that(index["vendor"]["sha"]).is_equal_to(_NEW_SHA)
    assert_that(manage_vendors.check(repo_root=repo_root)).is_zero()


def test_update_rejects_unknown_id(repo_root: Path) -> None:
    """Refuse to update a vendor id that is not present."""
    with pytest.raises(ValueError, match="Unknown vendor id"):
        manage_vendors.update(
            repo_root=repo_root,
            vendor_id="ghost",
            repo=None,
            sha=_NEW_SHA,
            skill_roots=None,
            license_name=None,
            homepage=None,
            display_ref=None,
        )


def test_refresh_reports_clean_after_bake(repo_root: Path) -> None:
    """Keep artifacts consistent so a follow-up check reports no drift."""
    manage_vendors.refresh(repo_root=repo_root)

    assert_that(manage_vendors.check(repo_root=repo_root)).is_zero()


def test_check_detects_registry_drift(repo_root: Path) -> None:
    """Report drift when the registry SHA diverges from baked artifacts."""
    registry_path = repo_root / "vendors.yaml"
    registry_path.write_text(
        registry_path.read_text(encoding="utf-8").replace(_EXISTING_SHA, _NEW_SHA),
        encoding="utf-8",
    )

    assert_that(manage_vendors.check(repo_root=repo_root)).is_equal_to(1)


def test_check_detects_plugin_bake_drift(repo_root: Path) -> None:
    """Report drift when only plugins-baked/ diverges from the lock."""
    coverage = repo_root / "plugins-baked" / "COVERAGE.md"
    coverage.write_text(
        coverage.read_text(encoding="utf-8") + "tamper\n",
        encoding="utf-8",
    )
    assert_that(manage_vendors.check(repo_root=repo_root)).is_equal_to(1)


def test_check_passes_when_plugins_baked_is_absent(repo_root: Path) -> None:
    """Skip plugin-tree drift when the publish-time bake output is missing."""
    shutil.rmtree(repo_root / "plugins-baked")
    shutil.rmtree(repo_root / "npm" / "ai-skills" / "data" / "plugins-baked")
    assert_that(manage_vendors.check(repo_root=repo_root)).is_zero()


def test_refresh_copies_baked_plugins_into_npm_package(repo_root: Path) -> None:
    """Package data receives a copy of plugins-baked after refresh."""
    source = repo_root / "plugins-baked" / "COVERAGE.md"
    dest = repo_root / "npm" / "ai-skills" / "data" / "plugins-baked" / "COVERAGE.md"
    assert_that(dest.is_file()).is_true()
    assert_that(dest.read_text(encoding="utf-8")).is_equal_to(
        source.read_text(encoding="utf-8"),
    )


def test_parser_help_mentions_plugin_trees() -> None:
    """refresh and check help strings mention plugin trees."""
    help_text = manage_vendors._build_parser().format_help()
    assert_that(help_text).contains("plugin trees")


def test_add_rolls_back_registry_when_rebake_fails(
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restore vendors.yaml when the post-write rebake raises."""
    registry_path = repo_root / "vendors.yaml"
    original = registry_path.read_text(encoding="utf-8")

    def _boom(*, vendor: Vendor) -> list[str]:
        """Simulate a GitHub fetch failure during rebake.

        Args:
            vendor: Vendor whose tree would normally be fetched.

        Raises:
            RuntimeError: Always, to emulate a network failure.
        """
        del vendor
        msg = "network failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(bake_vendor_indexes, "_fetch_tree_paths", _boom)

    with pytest.raises(RuntimeError, match="network failure"):
        manage_vendors.add(
            repo_root=repo_root,
            vendor_id="brand-new",
            repo="owner/brand-new",
            sha=_NEW_SHA,
            skill_roots=("skills",),
            license_name="MIT",
            homepage="https://github.com/owner/brand-new",
            display_ref=None,
        )

    assert_that(registry_path.read_text(encoding="utf-8")).is_equal_to(original)
    assert_that((repo_root / "vendor-indexes" / "brand-new.json").exists()).is_false()


def test_add_rolls_back_indexes_when_sync_fails(
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restore vendors.yaml and baked indexes when sync fails after bake."""
    registry_path = repo_root / "vendors.yaml"
    original_registry = registry_path.read_text(encoding="utf-8")
    existing_index = repo_root / "vendor-indexes" / "existing.json"
    original_index = existing_index.read_text(encoding="utf-8")
    original_notice = (repo_root / "NOTICE.md").read_text(encoding="utf-8")

    def _boom_sync(*, repo_root: Path, check_only: bool) -> int:
        """Simulate a sync failure after a successful rebake.

        Args:
            repo_root: Repository root that would be synchronized.
            check_only: Whether the sync would only verify artifacts.

        Raises:
            RuntimeError: Always, to emulate a partial sync write.
        """
        del check_only
        (repo_root / "NOTICE.md").write_text(
            "partially synchronized\n",
            encoding="utf-8",
        )
        msg = "sync failure"
        raise RuntimeError(msg)

    with monkeypatch.context() as sync_patch:
        sync_patch.setattr(manage_vendors, "_sync_artifacts", _boom_sync)
        with pytest.raises(RuntimeError, match="sync failure"):
            manage_vendors.add(
                repo_root=repo_root,
                vendor_id="brand-new",
                repo="owner/brand-new",
                sha=_NEW_SHA,
                skill_roots=("skills",),
                license_name="MIT",
                homepage="https://github.com/owner/brand-new",
                display_ref=None,
            )

    assert_that(registry_path.read_text(encoding="utf-8")).is_equal_to(
        original_registry
    )
    assert_that((repo_root / "vendor-indexes" / "brand-new.json").exists()).is_false()
    assert_that(existing_index.read_text(encoding="utf-8")).is_equal_to(original_index)
    assert_that((repo_root / "NOTICE.md").read_text(encoding="utf-8")).is_equal_to(
        original_notice,
    )
    assert_that(manage_vendors.check(repo_root=repo_root)).is_zero()


def test_update_rejects_unknown_registry_key(repo_root: Path) -> None:
    """Fail closed instead of silently dropping unknown registry keys."""
    registry_path = repo_root / "vendors.yaml"
    original = registry_path.read_text(encoding="utf-8")
    registry_path.write_text(original + "extra: dropped\n", encoding="utf-8")

    with pytest.raises((TypeError, ValueError)):
        manage_vendors.update(
            repo_root=repo_root,
            vendor_id="existing",
            repo=None,
            sha=_NEW_SHA,
            skill_roots=None,
            license_name=None,
            homepage=None,
            display_ref=None,
        )


def test_add_quotes_yaml_reserved_word_display_ref(repo_root: Path) -> None:
    """Quote reserved-word field values so they reload as strings, not bools."""
    exit_code = manage_vendors.main(
        [
            "add",
            "--repo-root",
            str(repo_root),
            "--id",
            "brand-new",
            "--repo",
            "owner/brand-new",
            "--sha",
            _NEW_SHA,
            "--skill-roots",
            "skills",
            "--license",
            "MIT",
            "--homepage",
            "https://github.com/owner/brand-new",
            "--display-ref",
            "yes",
        ],
    )

    assert_that(exit_code).is_zero()
    registry_text = (repo_root / "vendors.yaml").read_text(encoding="utf-8")
    assert_that(registry_text).contains('displayRef: "yes"')
    data = yaml.safe_load(registry_text)
    added = next(vendor for vendor in data["vendors"] if vendor["id"] == "brand-new")
    assert_that(added["displayRef"]).is_equal_to("yes")


def test_add_via_main_accepts_comma_separated_roots(repo_root: Path) -> None:
    """Support comma-separated --skill-roots through the CLI entrypoint."""
    exit_code = manage_vendors.main(
        [
            "add",
            "--repo-root",
            str(repo_root),
            "--id",
            "brand-new",
            "--repo",
            "owner/brand-new",
            "--sha",
            _NEW_SHA,
            "--skill-roots",
            "skills, plugins/*/skills",
            "--license",
            "MIT",
            "--homepage",
            "https://github.com/owner/brand-new",
        ],
    )

    assert_that(exit_code).is_zero()
    vendors = load_registry(registry_path=repo_root / "vendors.yaml")
    added = next(vendor for vendor in vendors if vendor.id == "brand-new")
    assert_that(added.skill_roots).is_equal_to(("skills", "plugins/*/skills"))


def test_add_via_main_rejects_empty_skill_roots(repo_root: Path) -> None:
    """Reject skill-root input that yields no non-empty entries."""
    registry_path = repo_root / "vendors.yaml"
    original = registry_path.read_text(encoding="utf-8")

    exit_code = manage_vendors.main(
        [
            "add",
            "--repo-root",
            str(repo_root),
            "--id",
            "brand-new",
            "--repo",
            "owner/brand-new",
            "--sha",
            _NEW_SHA,
            "--skill-roots",
            " , ",
            "--license",
            "MIT",
            "--homepage",
            "https://github.com/owner/brand-new",
        ],
    )

    assert_that(exit_code).is_equal_to(1)
    assert_that(registry_path.read_text(encoding="utf-8")).is_equal_to(original)


def test_update_preserves_plugin_slices(repo_root: Path) -> None:
    """SHA refresh must round-trip reviewed plugin slices instead of dropping them."""
    registry_path = repo_root / "vendors.yaml"
    contents = registry_path.read_text(encoding="utf-8")
    registry_path.write_text(
        contents.replace(
            "homepage: https://github.com/owner/existing\n",
            "homepage: https://github.com/owner/existing\n"
            "    plugins:\n"
            "      - id: existing-plugin\n"
            "        description: Existing vendor plugin.\n"
            "        skillsRoot: skills\n"
            '        skills: "*"\n'
            "        renameSkills:\n"
            "          teach: teach-existing\n"
            "        agents:\n"
            "          - comment-sicko\n",
        ),
        encoding="utf-8",
    )

    manage_vendors.update(
        repo_root=repo_root,
        vendor_id="existing",
        repo=None,
        sha=_NEW_SHA,
        skill_roots=None,
        license_name=None,
        homepage=None,
        display_ref=None,
    )

    vendors = load_registry(registry_path=registry_path)
    plugin = vendors[0].plugins[0]
    assert_that(plugin.id).is_equal_to("existing-plugin")
    assert_that(plugin.skills).is_equal_to("*")
    assert_that(plugin.rename_skills).is_equal_to((("teach", "teach-existing"),))
    assert_that(plugin.agents).is_equal_to(("comment-sicko",))
    assert_that(
        (repo_root / "plugins-baked" / "existing-plugin" / "skills" / "teach-existing")
        .joinpath("SKILL.md")
        .is_file(),
    ).is_true()
    skill_markdown = (
        repo_root / "plugins-baked" / "existing-plugin" / "skills" / "teach-existing"
    ).joinpath("SKILL.md")
    assert_that(skill_markdown.read_text(encoding="utf-8")).contains(
        "name: teach-existing",
    )
    assert_that(manage_vendors.check(repo_root=repo_root)).is_zero()
    dumped = registry_path.read_text(encoding="utf-8")
    assert_that(dumped).contains(
        "    plugins:\n"
        "      - id: existing-plugin\n"
        "        description: Existing vendor plugin.\n"
        "        skillsRoot: skills\n"
        '        skills: "*"\n'
        "        renameSkills:\n"
        "          teach: teach-existing\n"
        "        agents:\n"
        "          - comment-sicko\n"
        "    license: MIT\n",
    )


def test_update_preserves_skill_paths_and_extra_skills(repo_root: Path) -> None:
    """SHA refresh must round-trip path-list skills and extraSkills."""
    registry_path = repo_root / "vendors.yaml"
    contents = registry_path.read_text(encoding="utf-8")
    registry_path.write_text(
        contents.replace(
            "homepage: https://github.com/owner/existing\n",
            "homepage: https://github.com/owner/existing\n"
            "    plugins:\n"
            "      - id: path-plugin\n"
            "        description: Path-list vendor plugin.\n"
            "        skillsRoot: skills\n"
            "        skills:\n"
            "          - alpha\n"
            "          - nested/beta\n"
            "        extraSkills:\n"
            "          - extras/bonus\n",
        ),
        encoding="utf-8",
    )

    manage_vendors.update(
        repo_root=repo_root,
        vendor_id="existing",
        repo=None,
        sha=_NEW_SHA,
        skill_roots=None,
        license_name=None,
        homepage=None,
        display_ref=None,
    )

    plugin = load_registry(registry_path=registry_path)[0].plugins[0]
    assert_that(plugin.id).is_equal_to("path-plugin")
    assert_that(plugin.skills).is_equal_to(("alpha", "nested/beta"))
    assert_that(plugin.extra_skills).is_equal_to(("extras/bonus",))
    dumped = registry_path.read_text(encoding="utf-8")
    assert_that(dumped).contains(
        "    plugins:\n"
        "      - id: path-plugin\n"
        "        description: Path-list vendor plugin.\n"
        "        skillsRoot: skills\n"
        "        skills:\n"
        "          - alpha\n"
        "          - nested/beta\n"
        "        extraSkills:\n"
        "          - extras/bonus\n"
        "    license: MIT\n",
    )


def _vendor_for_dump(*, plugins: object) -> dict[str, object]:
    """Return a vendor mapping used to exercise dump-time plugin validation.

    Args:
        plugins: Raw ``plugins`` value to serialize.

    Returns:
        A camelCase vendor mapping for ``_dump_registry``.
    """
    return {
        "id": "existing",
        "repo": "owner/existing",
        "sha": _EXISTING_SHA,
        "skillRoots": ["skills"],
        "plugins": plugins,
        "license": "MIT",
        "homepage": "https://github.com/owner/existing",
    }


def test_dump_registry_rejects_non_list_plugins() -> None:
    """Dumping must fail closed instead of coercing invalid plugin values."""
    with pytest.raises(TypeError, match="plugins must be a list"):
        manage_vendors._dump_registry(
            vendors=[_vendor_for_dump(plugins=None)],
        )


def test_dump_registry_rejects_non_mapping_plugin() -> None:
    """Dumping must fail closed on a non-mapping plugin list item."""
    with pytest.raises(TypeError, match="plugins entries must be mappings"):
        manage_vendors._dump_registry(
            vendors=[_vendor_for_dump(plugins=["not-a-mapping"])],
        )


def test_dump_registry_rejects_unknown_plugin_field() -> None:
    """Dumping must fail closed if a plugin key is not in the dump order."""
    with pytest.raises(ValueError, match="unknown fields"):
        manage_vendors._dump_registry(
            vendors=[
                _vendor_for_dump(
                    plugins=[
                        {
                            "id": "path-plugin",
                            "description": "Path-list vendor plugin.",
                            "skillsRoot": "skills",
                            "skills": "*",
                            "mystery": True,
                        },
                    ],
                ),
            ],
        )


def test_write_registry_rejects_malformed_skills(tmp_path: Path) -> None:
    """The write path must fail closed when skills is neither '*' nor a list."""
    registry_path = tmp_path / "vendors.yaml"
    registry_path.write_text("---\nvendors: []\n", encoding="utf-8")
    with pytest.raises(TypeError, match=r'skills must be "\*" or a list'):
        manage_vendors._write_registry(
            registry_path=registry_path,
            vendors=[
                _vendor_for_dump(
                    plugins=[
                        {
                            "id": "path-plugin",
                            "description": "Path-list vendor plugin.",
                            "skillsRoot": "skills",
                            "skills": 123,
                        },
                    ],
                ),
            ],
        )
    assert_that(registry_path.read_text(encoding="utf-8")).is_equal_to(
        "---\nvendors: []\n",
    )


def test_restore_artifacts_prunes_empty_directories(tmp_path: Path) -> None:
    """Rollback must not leave skill directories without SKILL.md."""
    baked = tmp_path / "plugins-baked"
    skill = baked / "example-plugin" / "skills" / "alpha"
    skill.mkdir(parents=True)
    skill_markdown = skill / "SKILL.md"
    skill_markdown.write_text("old\n", encoding="utf-8")
    snapshot, directories = manage_vendors._snapshot_artifacts(paths=(baked,))
    beta = baked / "example-plugin" / "skills" / "beta"
    beta.mkdir()
    (beta / "SKILL.md").write_text("new\n", encoding="utf-8")

    manage_vendors._restore_artifacts(
        paths=(baked,),
        snapshot=snapshot,
        directories=directories,
    )

    assert_that(skill_markdown.read_text(encoding="utf-8")).is_equal_to("old\n")
    assert_that(beta.exists()).is_false()


def test_restore_artifacts_removes_root_absent_from_snapshot(
    tmp_path: Path,
) -> None:
    """Rollback must not leave a plugins-baked/ root that did not exist."""
    baked = tmp_path / "plugins-baked"
    snapshot, directories = manage_vendors._snapshot_artifacts(paths=(baked,))
    baked.mkdir()
    (baked / "COVERAGE.md").write_text("new\n", encoding="utf-8")

    manage_vendors._restore_artifacts(
        paths=(baked,),
        snapshot=snapshot,
        directories=directories,
    )

    assert_that(baked.exists()).is_false()


def test_restore_artifacts_keeps_empty_snapshotted_directories(
    tmp_path: Path,
) -> None:
    """Agent-only plugins keep an empty skills/ directory after rollback."""
    baked = tmp_path / "plugins-baked"
    plugin = baked / "example-plugin"
    skills = plugin / "skills"
    skills.mkdir(parents=True)
    (plugin / "plugin.json").write_text("{}\n", encoding="utf-8")
    snapshot, directories = manage_vendors._snapshot_artifacts(paths=(baked,))
    beta = skills / "beta"
    beta.mkdir()
    (beta / "SKILL.md").write_text("new\n", encoding="utf-8")

    manage_vendors._restore_artifacts(
        paths=(baked,),
        snapshot=snapshot,
        directories=directories,
    )

    assert_that(skills.is_dir()).is_true()
    assert_that(beta.exists()).is_false()
    assert_that(any(skills.iterdir())).is_false()


_PRODUCTION_LAYOUT = (
    "---\n"
    "vendors:\n"
    "  - id: existing\n"
    "    repo: owner/existing\n"
    f'    sha: "{_EXISTING_SHA}"\n'
    "    displayRef: latest\n"
    "    skillRoots:\n"
    "      - skills\n"
    "    license: MIT\n"
    "    homepage: https://github.com/owner/existing\n"
    "    plugins:\n"
    "      - id: existing-skills\n"
    "        # yamllint disable-line rule:line-length\n"
    "        description: Example vendor plugin.\n"
    "        skillsRoot: skills\n"
    '        skills: "*"\n'
)


def test_set_sha_preserves_comments_and_field_order(tmp_path: Path) -> None:
    """A pin bump edits only the target vendor ``sha`` line."""
    registry = tmp_path / "vendors.yaml"
    registry.write_text(_PRODUCTION_LAYOUT, encoding="utf-8")

    manage_vendors.set_sha(
        repo_root=tmp_path,
        vendor_id="existing",
        sha=_NEW_SHA,
    )

    text = registry.read_text(encoding="utf-8")
    assert_that(text).contains(f'sha: "{_NEW_SHA}"')
    assert_that(text).does_not_contain(_EXISTING_SHA)
    assert_that(text).contains("# yamllint disable-line rule:line-length")
    license_at = text.index("    license: MIT")
    plugins_at = text.index("    plugins:")
    assert_that(license_at).is_less_than(plugins_at)
    loaded = load_registry(registry_path=registry)
    assert_that(loaded[0].sha).is_equal_to(_NEW_SHA)


def test_set_sha_rejects_unknown_vendor(tmp_path: Path) -> None:
    """Unknown vendor ids leave vendors.yaml unchanged."""
    registry = tmp_path / "vendors.yaml"
    registry.write_text(_PRODUCTION_LAYOUT, encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown vendor id"):
        manage_vendors.set_sha(
            repo_root=tmp_path,
            vendor_id="missing",
            sha=_NEW_SHA,
        )

    assert_that(registry.read_text(encoding="utf-8")).is_equal_to(_PRODUCTION_LAYOUT)
