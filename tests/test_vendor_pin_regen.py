"""Offline coverage of the Renovate vendor regeneration and signed API writes."""

from __future__ import annotations

import base64
import json
import re
import subprocess  # nosec B404 - isolated local Git fixtures, no shell
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
import yaml
from assertpy import assert_that
from ci import create_signed_commit
from vendor_registry.registry import load_registry

_ROOT = Path(__file__).resolve().parents[1]
_REPOSITORY = "owner/catalog"
_BRANCH = "renovate/vendor-pin"
_NEW_HEAD = "a" * 40


@pytest.fixture
def git_tree(tmp_path: Path) -> Path:
    """Create an isolated committed catalog for real Git diff tests.

    Args:
        tmp_path: Temporary directory with no remote or signing identity.

    Returns:
        Root of a local-only Git repository.
    """
    (tmp_path / "vendor-indexes").mkdir()
    (tmp_path / "vendor-indexes" / "old.json").write_bytes(b"old\n")
    (tmp_path / "NOTICE.md").write_bytes(b"before\n")
    for args in (
        ["init", "--quiet"],
        ["add", "."],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
    ):
        subprocess.run(  # nosec B603 B607 - local fixture, fixed git executable
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
    return tmp_path


def _head(repo_root: Path) -> str:
    """Read the fixture commit SHA.

    Args:
        repo_root: Local fixture root.

    Returns:
        HEAD SHA.
    """
    return str(
        create_signed_commit._git(
            repo_root=repo_root,
            args=["rev-parse", "HEAD"],
        )
        .decode()
        .strip(),
    )


@pytest.fixture
def api(git_tree: Path) -> Mock:
    """Inject an HTTP client with no network or GitHub side effects.

    Args:
        git_tree: Local Git fixture whose head the fake PR tracks.

    Returns:
        Recording mock with successful default API responses.
    """

    def request(*, method: str, path: str, payload: object = None) -> Any:
        del method, payload
        if path.endswith("/pulls/522"):
            return {
                "state": "open",
                "head": {
                    "sha": _head(git_tree),
                    "ref": _BRANCH,
                    "repo": {"full_name": _REPOSITORY},
                },
            }
        if path == "/graphql":
            return {"data": {"createCommitOnBranch": {"commit": {"oid": _NEW_HEAD}}}}
        return []

    return Mock(side_effect=request)


def _publish(
    *,
    repo_root: Path,
    request: Mock,
    expected_head: str | None = None,
) -> str:
    """Publish fixture changes through the injected HTTP client.

    Args:
        repo_root: Fixture checkout root.
        request: Fake HTTP client.
        expected_head: Override for stale checkout tests.

    Returns:
        Commit OID from the helper.
    """
    return str(
        create_signed_commit.publish(
            repo_root=repo_root,
            repository=_REPOSITORY,
            branch=_BRANCH,
            expected_head=expected_head
            if expected_head is not None
            else _head(repo_root),
            pr_number=522,
            summary="# Bake summary\n",
            request=request,
        ),
    )


def test_renovate_captures_every_explicit_vendor_branch() -> None:
    """The actual Renovate regex extracts all pins and their branch refs."""
    config = json.loads((_ROOT / "renovate.json").read_text(encoding="utf-8"))
    manager = next(
        item
        for item in config["customManagers"]
        if item.get("datasourceTemplate") == "git-refs"
    )
    pattern = manager["matchStrings"][0].replace("(?<", "(?P<")
    matches = [
        match.groupdict()
        for match in re.finditer(
            pattern,
            (_ROOT / "vendors.yaml").read_text(encoding="utf-8"),
        )
    ]
    vendors = load_registry(registry_path=_ROOT / "vendors.yaml")
    assert_that(matches).is_equal_to(
        [
            {
                "depName": vendor.repo,
                "currentDigest": vendor.sha,
                "currentValue": vendor.branch,
            }
            for vendor in vendors
        ],
    )
    assert_that(len(matches)).is_equal_to(5)
    assert_that(manager).does_not_contain_key("currentValueTemplate")
    for vendor in vendors:
        assert_that(vendor.branch).is_equal_to("main")


def test_registry_branch_follows_sha() -> None:
    """Keep the documented Renovate serialization contract for every entry."""
    lines = (_ROOT / "vendors.yaml").read_text(encoding="utf-8").splitlines()
    sha_lines = [
        index for index, line in enumerate(lines) if line.startswith("    sha:")
    ]
    assert_that(sha_lines).is_length(5)
    assert_that(
        all(lines[index + 1] == "    branch: main" for index in sha_lines),
    ).is_true()


def test_signed_commit_payload_handles_add_modify_rename_delete(
    git_tree: Path,
    api: Mock,
) -> None:
    """GraphQL carries base64 bytes, deletions, and the original event head."""
    expected_head = _head(git_tree)
    (git_tree / "NOTICE.md").write_bytes(b"after\n")
    (git_tree / "vendor-indexes" / "old.json").rename(
        git_tree / "vendor-indexes" / "renamed.json",
    )
    (git_tree / "vendor-indexes" / "new.json").write_bytes(b"\x00binary\xff")

    assert_that(_publish(repo_root=git_tree, request=api)).is_equal_to(_NEW_HEAD)
    mutation = next(
        call.kwargs["payload"]
        for call in api.call_args_list
        if call.kwargs["path"] == "/graphql"
    )
    data = mutation["variables"]["input"]
    assert_that(mutation["query"]).contains("createCommitOnBranch")
    assert_that(data["expectedHeadOid"]).is_equal_to(expected_head)
    assert_that(data["branch"]).is_equal_to(
        {"repositoryNameWithOwner": _REPOSITORY, "branchName": _BRANCH},
    )
    changes = data["fileChanges"]
    assert_that(changes["deletions"]).is_equal_to([{"path": "vendor-indexes/old.json"}])
    decoded = {
        item["path"]: base64.b64decode(item["contents"])
        for item in changes["additions"]
    }
    assert_that(decoded).is_equal_to(
        {
            "NOTICE.md": b"after\n",
            "vendor-indexes/new.json": b"\x00binary\xff",
            "vendor-indexes/renamed.json": b"old\n",
        },
    )
    assert_that(_head(git_tree)).is_equal_to(expected_head)


def test_no_diff_posts_summary_without_commit(git_tree: Path, api: Mock) -> None:
    """A synchronize run with current artifacts creates no empty commit."""
    assert_that(_publish(repo_root=git_tree, request=api)).is_equal_to(_head(git_tree))
    posts = [
        call.kwargs for call in api.call_args_list if call.kwargs["method"] == "POST"
    ]
    assert_that(posts).is_length(1)
    assert_that(posts[0]["path"]).ends_with("/issues/522/comments")


def test_stale_checkout_makes_no_api_calls(git_tree: Path, api: Mock) -> None:
    """Never infer a newer expected head from a different local checkout."""
    with pytest.raises(ValueError, match="Checkout must match"):
        _publish(repo_root=git_tree, request=api, expected_head="b" * 40)
    assert_that(api.call_count).is_zero()


@pytest.mark.parametrize("field", ["sha", "ref", "repository", "state"])
def test_remote_pr_mismatch_refuses_writes(
    git_tree: Path,
    api: Mock,
    field: str,
) -> None:
    """Closed, moved, renamed, and fork PRs cannot receive a commit or comment."""
    pr = api.side_effect(method="GET", path="/pulls/522")
    if field == "repository":
        pr["head"]["repo"]["full_name"] = "someone/fork"
    elif field == "state":
        pr["state"] = "closed"
    else:
        pr["head"][field] = "different"
    api.side_effect = None
    api.return_value = pr
    with pytest.raises(ValueError, match="PR head has changed"):
        _publish(repo_root=git_tree, request=api)
    assert_that(api.call_count).is_equal_to(1)


@pytest.mark.parametrize(
    "result",
    [
        {"errors": [{"message": "Head moved"}]},
        {"data": {"createCommitOnBranch": None}},
        {"errors": [{"message": "denied"}], "data": None},
        {"data": None},
    ],
)
def test_graphql_failure_does_not_retry_or_comment(
    git_tree: Path,
    api: Mock,
    result: dict[str, Any],
) -> None:
    """GraphQL races and permission failures fail closed without token fallback."""
    (git_tree / "NOTICE.md").write_text("changed", encoding="utf-8")
    pr = api.side_effect(method="GET", path="/pulls/522")
    api.side_effect = [pr, result]
    with pytest.raises(RuntimeError, match="no retry"):
        _publish(repo_root=git_tree, request=api)
    assert_that(api.call_count).is_equal_to(2)


@pytest.mark.parametrize(
    "name",
    ["vendors.yaml", "scripts/unsafe.py", "plugins-baked/file"],
)
def test_non_generated_change_is_rejected(git_tree: Path, name: str) -> None:
    """Commit publication is restricted to generated catalog data."""
    path = git_tree / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("unexpected", encoding="utf-8")
    with pytest.raises(ValueError, match="non-generated"):
        create_signed_commit.file_changes(repo_root=git_tree)


def test_symlink_is_rejected(git_tree: Path) -> None:
    """A generated path cannot cause publication of an external file."""
    (git_tree / "vendor-indexes" / "link.json").symlink_to(git_tree / "NOTICE.md")
    with pytest.raises(ValueError, match="symlink"):
        create_signed_commit.file_changes(repo_root=git_tree)


@pytest.mark.parametrize("same_body", [True, False])
def test_sticky_summary_updates_only_own_comment(same_body: bool) -> None:
    """Respect comment authorship, pagination, and unchanged comment bodies."""
    summary = "# Summary\n"
    body = f"<!-- vendor-pin-regen -->\n{summary}"
    other = {"id": 1, "body": body, "user": {"login": "someone"}}
    own = {
        "id": 2,
        "body": body if same_body else "<!-- vendor-pin-regen -->\nold",
        "user": {"login": "lgtm-release-bot[bot]"},
    }
    request = Mock(side_effect=[[other] * 100, [own], {}])
    create_signed_commit.upsert_summary(
        repository=_REPOSITORY,
        pr_number=522,
        summary=summary,
        request=request,
    )
    assert_that(request.call_count).is_equal_to(2 if same_body else 3)
    if not same_body:
        assert_that(request.call_args.kwargs).is_equal_to(
            {
                "method": "PATCH",
                "path": f"/repos/{_REPOSITORY}/issues/comments/2",
                "payload": {"body": body},
            },
        )


def test_workflow_limits_credentials_to_same_repo_renovate_heads() -> None:
    """The regeneration job uses an exact head and App token only for publication."""
    workflow = yaml.safe_load(
        (_ROOT / ".github/workflows/vendor-pin-regen.yml").read_text(encoding="utf-8"),
    )
    assert_that(workflow["on"]["pull_request"]).is_equal_to(
        {"types": ["opened", "synchronize"], "paths": ["vendors.yaml"]},
    )
    job = workflow["jobs"]["regenerate"]
    assert_that(job["if"]).contains(
        "startsWith(github.head_ref, 'renovate/')",
        "head.repo.full_name == github.repository",
        "renovate[bot]",
    )
    steps = job["steps"]
    actions = [step for step in steps if "uses" in step]
    assert_that(
        all(re.search(r"@[0-9a-f]{40}$", step["uses"]) for step in actions),
    ).is_true()
    harden = next(
        step
        for step in actions
        if step["uses"].startswith("step-security/harden-runner@")
    )
    assert_that(harden["with"]["egress-policy"]).is_equal_to("block")
    checkout = next(
        step for step in actions if step["uses"].startswith("actions/checkout@")
    )
    assert_that(checkout["with"]["ref"]).is_equal_to(
        "${{ github.event.pull_request.head.sha }}",
    )
    assert_that(checkout["with"]["persist-credentials"]).is_false()
    publisher = steps[-1]
    assert_that(publisher["env"]["GH_TOKEN"]).is_equal_to(
        "${{ steps.app-token.outputs.token }}",
    )
    assert_that(publisher["env"]).does_not_contain_key("GITHUB_TOKEN")
