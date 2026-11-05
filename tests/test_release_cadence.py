"""Keep milestone release merges operator-controlled without stopping preparation."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from assertpy import assert_that


@pytest.fixture
def release_workflows() -> dict[str, Any]:
    """Parse the real release callers and publication workflows offline."""
    workflows = Path(__file__).resolve().parents[1] / ".github/workflows"
    return {
        name: yaml.safe_load((workflows / f"{name}.yml").read_text(encoding="utf-8"))
        for name in (
            "release-version-pr",
            "release-auto-tag",
            "release-manifest",
            "release-sbom",
            "publish-npm",
        )
    }


def test_version_pr_requires_operator_merge(release_workflows: dict[str, Any]) -> None:
    """Main merges must never re-enable automatic merging of a held version PR."""
    job = release_workflows["release-version-pr"]["jobs"]["version-pr"]
    assert_that(job["with"]["auto-merge"]).is_same_as(False)


def test_version_pr_preparation_stays_enabled(
    release_workflows: dict[str, Any],
) -> None:
    """Main pushes and manual dispatch still prepare PRs through pinned tooling."""
    workflow = release_workflows["release-version-pr"]
    assert_that(workflow["on"]).is_equal_to(
        {"push": {"branches": ["main"]}, "workflow_dispatch": None},
    )
    job = workflow["jobs"]["version-pr"]
    assert_that(job).does_not_contain_key("if")
    assert_that(job["uses"]).matches(
        r"^lgtm-hq/lgtm-ci/\.github/workflows/"
        r"reusable-release-version-pr\.yml@[0-9a-f]{40}$",
    )
    assert_that(job["with"]["tooling-ref"]).is_equal_to(job["uses"].rsplit("@", 1)[1])
    assert_that(job["with"]["egress-policy"]).is_equal_to("block")
    assert_that(job["with"]).contains_entry(
        {"max-bump": "minor"},
        {"ecosystems": "python"},
        {"version-update-script": "scripts/ci/update_release_version.sh"},
        {"egress-preset": "pypi"},
    )
    assert_that(job["secrets"]).is_equal_to(
        {
            "RELEASE_APP_ID": "${{ secrets.RELEASE_APP_ID }}",
            "RELEASE_APP_PRIVATE_KEY": "${{ secrets.RELEASE_APP_PRIVATE_KEY }}",
        },
    )
    assert_that(job["permissions"]).is_equal_to(
        {
            "contents": "write",
            "pull-requests": "write",
            "actions": "read",
            "issues": "write",
        },
    )


def test_release_tagging_stays_enabled(release_workflows: dict[str, Any]) -> None:
    """Merging a prepared changelog still triggers normal tag/release creation."""
    workflow = release_workflows["release-auto-tag"]
    assert_that(workflow["on"]["push"]).is_equal_to(
        {"branches": ["main"], "paths": ["CHANGELOG.md"]},
    )
    assert_that(workflow["on"]).contains_key("workflow_dispatch")
    job = workflow["jobs"]["auto-tag"]
    assert_that(job).does_not_contain_key("if")
    assert_that(job["uses"]).matches(
        r"^lgtm-hq/lgtm-ci/\.github/workflows/"
        r"reusable-release-auto-tag\.yml@[0-9a-f]{40}$",
    )
    assert_that(job["with"]["tooling-ref"]).is_equal_to(job["uses"].rsplit("@", 1)[1])
    assert_that(job["with"]["egress-policy"]).is_equal_to("block")


@pytest.mark.parametrize("name", ["release-manifest", "release-sbom", "publish-npm"])
def test_published_release_consumers_stay_enabled(
    release_workflows: dict[str, Any],
    name: str,
) -> None:
    """Published releases and manual dispatch retain all publication consumers."""
    workflow = release_workflows[name]
    assert_that(workflow["on"]["release"]).is_equal_to({"types": ["published"]})
    assert_that(workflow["on"]).contains_key("workflow_dispatch")
