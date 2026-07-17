"""Tests for the vendor management CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from assertpy import assert_that

import bake_vendor_indexes
import manage_vendors
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
        "---\ngroups: {}\n",
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
        del repo_root, check_only
        msg = "sync failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(manage_vendors, "_sync_artifacts", _boom_sync)

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
    monkeypatch.undo()
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
