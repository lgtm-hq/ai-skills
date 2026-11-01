"""Offline coverage of the Renovate vendor regeneration and signed API writes."""

from __future__ import annotations

import base64
import json
import re
import subprocess  # nosec B404 - isolated local Git fixtures, no shell
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import manage_vendors
import pytest
import yaml
from assertpy import assert_that
from ci import create_signed_commit, vendor_pin_artifact
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
            artifact_directory=_write_artifact(repo_root=repo_root),
            repository=_REPOSITORY,
            branch=_BRANCH,
            expected_head=(
                expected_head if expected_head is not None else _head(repo_root)
            ),
            pr_number=522,
            request=request,
        ),
    )


def _write_artifact(*, repo_root: Path, status: int = 0) -> Path:
    """Package fixture output outside its checkout.

    Args:
        repo_root: Fixture checkout root.
        status: Summary collision status.

    Returns:
        Isolated envelope directory.
    """
    directory = repo_root.parent / f"{repo_root.name}-artifact"
    directory.mkdir(exist_ok=True)
    (directory / vendor_pin_artifact.ARTIFACT_NAME).write_text(
        json.dumps(
            {
                "head": _head(repo_root),
                "summary": "# Bake summary\n",
                "status": status,
                "fileChanges": create_signed_commit.file_changes(repo_root=repo_root),
            }
        ),
        encoding="utf-8",
    )
    return directory


@pytest.fixture
def renovate_vendor_manager() -> dict[str, Any]:
    """Read the actual Renovate manager for vendor refs.

    Returns:
        The git-refs custom manager configuration.
    """
    config = json.loads((_ROOT / "renovate.json").read_text(encoding="utf-8"))
    return next(
        item
        for item in config["customManagers"]
        if item.get("datasourceTemplate") == "git-refs"
    )


def test_renovate_captures_every_explicit_vendor_branch(
    renovate_vendor_manager: dict[str, Any],
) -> None:
    """The actual Renovate regex extracts all pins and their branch refs."""
    pattern = renovate_vendor_manager["matchStrings"][0].replace("(?<", "(?P<")
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
    assert_that(renovate_vendor_manager).does_not_contain_key("currentValueTemplate")
    for vendor in vendors:
        assert_that(vendor.branch).is_equal_to("main")


def test_renovate_vendor_pattern_uses_re2_subset(
    renovate_vendor_manager: dict[str, Any],
) -> None:
    """Keep the Python matching smoke tests free of RE2-unsupported constructs."""
    assert_that(renovate_vendor_manager["matchStrings"][0]).does_not_contain(
        "(?=",
        "(?!",
        "(?<=",
        "(?<!",
        "(?>",
        r"\1",
        r"\k",
        r"\g",
    )


@pytest.mark.parametrize(
    "branch",
    [
        "main",
        "release/next",
        "123",
        "1.2",
        "true",
        "False",
        "yes",
        "null",
        "2026-10-31",
    ],
    ids=[
        "plain",
        "slash",
        "integer",
        "decimal",
        "true",
        "false",
        "yes",
        "null",
        "date",
    ],
)
def test_renovate_captures_registry_writer_branch(
    tmp_path: Path,
    renovate_vendor_manager: dict[str, Any],
    branch: str,
) -> None:
    """Capture branch names without the quotes emitted by the registry writer."""
    registry_path = tmp_path / "vendors.yaml"
    vendor = manage_vendors._build_vendor_mapping(
        vendor_id="example",
        repo="owner/example",
        sha=_NEW_HEAD,
        branch=branch,
        skill_roots=("skills",),
        license_name="MIT",
        homepage="https://github.com/owner/example",
        display_ref=None,
    )
    manage_vendors._write_registry(registry_path=registry_path, vendors=[vendor])
    pattern = renovate_vendor_manager["matchStrings"][0].replace("(?<", "(?P<")
    matches = list(re.finditer(pattern, registry_path.read_text(encoding="utf-8")))

    assert_that(load_registry(registry_path=registry_path)[0].branch).is_equal_to(
        branch
    )
    assert_that(matches).is_length(1)
    assert_that(matches[0].groupdict()).is_equal_to(
        {
            "depName": "owner/example",
            "currentDigest": _NEW_HEAD,
            "currentValue": branch,
        },
    )


@pytest.mark.parametrize(
    "branch_scalar", ["release/next", "'release/next'", '"release/next"']
)
@pytest.mark.parametrize(
    "comment",
    ["", " # upstream default", "\t # upstream 'default' (\"main\")"],
    ids=["no-comment", "space-comment", "tab-comment-with-quotes"],
)
@pytest.mark.parametrize("line_ending", ["\n", "\r\n", ""], ids=["lf", "crlf", "eof"])
def test_renovate_captures_yaml_branch_quote_styles(
    renovate_vendor_manager: dict[str, Any],
    branch_scalar: str,
    comment: str,
    line_ending: str,
) -> None:
    """Capture complete YAML scalars with optional comments and line endings."""
    text = (
        f'repo: owner/example\n    sha: "{_NEW_HEAD}"\n'
        f"    branch: {branch_scalar}{comment}{line_ending}"
    )
    pattern = renovate_vendor_manager["matchStrings"][0].replace("(?<", "(?P<")
    matches = list(re.finditer(pattern, text))

    assert_that(matches).is_length(1)
    assert_that(matches[0].group("currentValue")).is_equal_to("release/next")


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
    with pytest.raises(ValueError, match="expected PR head"):
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


def test_workflow_isolates_credentials_from_pr_head_code() -> None:
    """Only base code runs in the token job, with no shared caches or overlay."""
    workflow = yaml.safe_load(
        (_ROOT / ".github/workflows/vendor-pin-regen.yml").read_text(encoding="utf-8"),
    )
    assert_that(workflow["on"]["pull_request"]).is_equal_to(
        {"types": ["opened", "synchronize"], "paths": ["vendors.yaml"]},
    )
    for name, ref in [("regenerate", "head"), ("publish", "base")]:
        job = workflow["jobs"][name]
        assert_that(job["if"]).contains(
            "startsWith(github.head_ref, 'renovate/')",
            "head.repo.full_name == github.repository",
            "pull_request.user.login == 'renovate[bot]'",
            'contains(fromJSON(\'["renovate[bot]","lgtm-release-bot[bot]"]\')',
            "github.triggering_actor",
        )
        assert_that(job["permissions"]).is_equal_to({"contents": "read"})
        steps = job["steps"]
        actions = [step for step in steps if "uses" in step]
        for step in actions:
            assert_that(step["uses"]).matches(r"@[0-9a-f]{40}$")
        assert_that(actions[0]["with"]["egress-policy"]).is_equal_to("block")
        assert_that(actions[0]["with"]["allowed-endpoints"].split()).contains(
            "raw.githubusercontent.com:443",
        )
        checkouts = [
            step for step in actions if step["uses"].startswith("actions/checkout@")
        ]
        assert_that(checkouts).is_length(1)
        assert_that(checkouts[0]["with"]["ref"]).is_equal_to(
            f"${{{{ github.event.pull_request.{ref}.sha }}}}",
        )
        assert_that(checkouts[0]["with"]["persist-credentials"]).is_false()
    regen = workflow["jobs"]["regenerate"]
    assert_that(json.dumps(regen)).does_not_contain("secrets.", "app-token")
    publish = workflow["jobs"]["publish"]
    assert_that(publish["needs"]).is_equal_to("regenerate")
    for step in publish["steps"]:
        if "run" in step:
            assert_that(step["env"]["ARTIFACT_DIR"]).starts_with("${{ runner.temp }}/")
            assert_that(step["run"]).starts_with(
                "uv run --no-project python scripts/ci/create_signed_commit.py",
            )
            assert_that(step["run"]).does_not_contain("git", "sync", "install")
        if "uses" in step:
            assert_that(step["uses"]).does_not_contain("actions/cache@")
            if step["uses"].startswith("astral-sh/setup-uv@"):
                assert_that(step["with"]["enable-cache"]).is_false()
            if step["uses"].startswith("actions/download-artifact@"):
                assert_that(step["with"]["path"]).is_equal_to(
                    "${{ runner.temp }}/vendor-pin-input",
                )
    steps = publish["steps"]
    validation = next(
        i for i, step in enumerate(steps) if "--validate-only" in step.get("run", "")
    )
    token = next(i for i, step in enumerate(steps) if step.get("id") == "app-token")
    assert_that(validation).is_less_than(token)
    publisher = steps[-1]
    assert_that(publisher["env"]["GH_TOKEN"]).is_equal_to(
        "${{ steps.app-token.outputs.token }}",
    )
    assert_that(publisher["env"]).does_not_contain_key("GITHUB_TOKEN")


@pytest.mark.parametrize("name", ["NOTICE.md", "vendor-indexes/nested/file.json"])
def test_symlinks_above_repo_do_not_reject_files(git_tree: Path, name: str) -> None:
    """A symlinked runner workspace is permitted above the repository boundary."""
    path = git_tree / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("changed", encoding="utf-8")
    alias = git_tree.parent / f"{git_tree.name}-workspace-link"
    alias.symlink_to(git_tree.parent, target_is_directory=True)
    changes = create_signed_commit.file_changes(repo_root=alias / git_tree.name)
    assert_that([item["path"] for item in changes["additions"]]).contains(name)


def test_symlink_directory_inside_repo_is_rejected(git_tree: Path) -> None:
    """The boundary exception never permits links inside generated directories."""
    (git_tree / "vendor-indexes/sub").symlink_to(git_tree, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        create_signed_commit.file_changes(repo_root=git_tree)


@pytest.mark.parametrize("kind", ["additions", "deletions"])
@pytest.mark.parametrize(
    "name",
    [
        "scripts/ci/create_signed_commit.py",
        ".venv/bin/python",
        "vendors.yaml",
        "/NOTICE.md",
        "vendor-indexes/../scripts/unsafe.py",
        "vendor-indexes/./x",
        "vendor-indexes//x",
        "npm/ai-skills/data/../../bin/skill.js",
        "vendor-indexes/.git/config",
        "vendor-indexes/x\\y",
        "vendor-indexes/a\x01",
        "npm/ai-skills/data/plugins-baked/plugin/hook.py",
    ],
)
def test_artifact_revalidates_addition_and_deletion_paths(
    git_tree: Path,
    api: Mock,
    kind: str,
    name: str,
) -> None:
    """A malicious artifact cannot write or delete executable/traversal paths."""
    directory = _write_artifact(repo_root=git_tree)
    path = directory / vendor_pin_artifact.ARTIFACT_NAME
    payload = json.loads(path.read_text())
    item = {"path": name}
    if kind == "additions":
        item["contents"] = base64.b64encode(b"untrusted code").decode()
    payload["fileChanges"][kind] = [item]
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="non-generated or noncanonical"):
        create_signed_commit.publish(
            artifact_directory=directory,
            repository=_REPOSITORY,
            branch=_BRANCH,
            expected_head=_head(git_tree),
            pr_number=522,
            request=api,
        )
    assert_that(api.call_count).is_zero()


@pytest.mark.parametrize(
    "tamper",
    [
        "root-symlink",
        "file-symlink",
        "extra-file",
        "extra-directory",
        "invalid-base64",
        "duplicate-path",
        "wrong-head",
        "bad-status",
        "collision-changes",
        "extra-key",
        "not-a-file",
    ],
)
def test_malformed_artifacts_make_no_api_calls(
    git_tree: Path,
    api: Mock,
    tamper: str,
) -> None:
    """Untrusted metadata, filesystem entries, and change records fail closed."""
    (git_tree / "NOTICE.md").write_text("changed")
    directory = _write_artifact(repo_root=git_tree)
    path = directory / vendor_pin_artifact.ARTIFACT_NAME
    payload = json.loads(path.read_text())
    if tamper == "root-symlink":
        alias = directory.with_name("artifact-alias")
        alias.symlink_to(directory, target_is_directory=True)
        directory = alias
    elif tamper == "file-symlink":
        original = path.with_name("original")
        path.rename(original)
        path.symlink_to(original)
    elif tamper == "extra-file":
        (directory / "helper.py").write_text("untrusted code")
    elif tamper == "extra-directory":
        (directory / "scripts").mkdir()
    elif tamper == "not-a-file":
        path.unlink()
        path.mkdir()
    else:
        if tamper == "invalid-base64":
            payload["fileChanges"]["additions"][0]["contents"] = "!!bad!!"
        elif tamper == "duplicate-path":
            payload["fileChanges"]["deletions"] = [{"path": "NOTICE.md"}]
        elif tamper == "wrong-head":
            payload["head"] = "b" * 40
        elif tamper == "bad-status":
            payload["status"] = True
        elif tamper == "collision-changes":
            payload["status"] = 1
        else:
            payload["run"] = "untrusted code"
        path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        create_signed_commit.publish(
            artifact_directory=directory,
            repository=_REPOSITORY,
            branch=_BRANCH,
            expected_head=_head(git_tree),
            pr_number=522,
            request=api,
        )
    assert_that(api.call_count).is_zero()


def test_payload_budget_precedes_every_api_call(
    git_tree: Path,
    api: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The combined base64 budget is enforced even across multiple additions."""
    (git_tree / "NOTICE.md").write_bytes(b"abc")
    (git_tree / "vendor-indexes/old.json").write_bytes(b"def")
    directory = _write_artifact(repo_root=git_tree)
    monkeypatch.setattr(vendor_pin_artifact, "MAX_BASE64_BYTES", 7)
    with pytest.raises(ValueError, match="Combined base64 payload exceeds 7 bytes"):
        create_signed_commit.publish(
            artifact_directory=directory,
            repository=_REPOSITORY,
            branch=_BRANCH,
            expected_head=_head(git_tree),
            pr_number=522,
            request=api,
        )
    assert_that(api.call_count).is_zero()


def test_graphql_errors_explain_failure(git_tree: Path, api: Mock) -> None:
    """Surface all GraphQL error messages without retrying against a moved head."""
    (git_tree / "NOTICE.md").write_text("changed")
    pr = api.side_effect(method="GET", path="/pulls/522")
    api.side_effect = [
        pr,
        {"errors": [{"message": "Head moved"}, {"message": "denied"}]},
    ]
    with pytest.raises(RuntimeError, match="Head moved; denied"):
        _publish(repo_root=git_tree, request=api)
    assert_that(api.call_count).is_equal_to(2)


def test_cli_refuses_artifact_inside_trusted_checkout(
    git_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even configuration mistakes cannot turn the download into a code overlay."""
    monkeypatch.chdir(git_tree)
    monkeypatch.setenv("ARTIFACT_DIR", str(git_tree / "input"))
    assert_that(create_signed_commit.main(["--validate-only"])).is_equal_to(1)


@pytest.fixture
def regen_runner(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Provide a shell harness with fake uv/git and no network or vendor code.

    Args:
        tmp_path: Isolated fixture directory.

    Returns:
        Harness root and minimal process environment.
    """
    binary = tmp_path / "bin"
    binary.mkdir()
    uv = binary / "uv"
    uv.write_text("""#!/bin/bash
set -euo pipefail
printf '%s\\n' "$*" >> "$CALL_LOG"
case "$*" in
  *repin_vendor.py*)
    printf '%s\\n' "$*" > "$BASELINE_LOG"
    if [[ "${SUMMARY_FAIL:-0}" == 1 ]]; then exit 1; fi
    echo summary > "$SUMMARY_PATH"
    exit "${COLLISION_STATUS:-0}"
    ;;
  *manage_vendors.py*)
    echo partial > partial-output
    exit "${REFRESH_STATUS:-0}"
    ;;
  *vendor_pin_artifact.py*)
    echo "$SUMMARY_STATUS" > "$ARTIFACT_DIR/publication.json"
    ;;
esac
""")
    uv.chmod(0o755)
    git = binary / "git"
    git.write_text(
        '#!/bin/bash\necho "merge-base $*" >> "$CALL_LOG"\necho merge-base-sha\n'
    )
    git.chmod(0o755)
    env = {
        "PATH": f"{binary}:/usr/bin:/bin",
        "SUMMARY_PATH": str(tmp_path / "summary.md"),
        "ARTIFACT_DIR": str(tmp_path / "artifact"),
        "BASE_SHA": "base-tip-sha",
        "CALL_LOG": str(tmp_path / "calls"),
        "BASELINE_LOG": str(tmp_path / "baseline"),
    }
    return tmp_path, env


@pytest.mark.parametrize("failure", ["refresh", "summary"])
def test_regeneration_failure_never_packages_partial_output(
    regen_runner: tuple[Path, dict[str, str]],
    failure: str,
) -> None:
    """A complete summary cannot excuse a subsequent hard refresh failure."""
    root, env = regen_runner
    Path(env["SUMMARY_PATH"]).write_text("stale summary")
    directory = Path(env["ARTIFACT_DIR"])
    directory.mkdir()
    (directory / "publication.json").write_text("stale output")
    env["REFRESH_STATUS" if failure == "refresh" else "SUMMARY_FAIL"] = "1"
    result = subprocess.run(  # nosec B603 B607 - fixed local shell harness
        ["bash", str(_ROOT / "scripts/ci/vendor_pin_regen.sh")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert_that(result.returncode).is_not_zero()
    assert_that((directory / "publication.json").exists()).is_false()
    assert_that(Path(env["CALL_LOG"]).read_text()).does_not_contain(
        "vendor_pin_artifact.py"
    )
    if failure == "refresh":
        assert_that((root / "partial-output").exists()).is_true()


@pytest.mark.parametrize("collision", [False, True])
def test_regeneration_uses_merge_base_and_preserves_collision_report(
    regen_runner: tuple[Path, dict[str, str]],
    collision: bool,
) -> None:
    """The baseline is computed by Git, and collisions package a report alone."""
    root, env = regen_runner
    env["COLLISION_STATUS"] = str(int(collision))
    result = subprocess.run(  # nosec B603 B607 - fixed local shell harness
        ["bash", str(_ROOT / "scripts/ci/vendor_pin_regen.sh")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert_that(result.returncode).described_as(result.stderr).is_zero()
    assert_that(Path(env["BASELINE_LOG"]).read_text()).contains(
        "--baseline-ref merge-base-sha"
    )
    assert_that(Path(env["CALL_LOG"]).read_text()).contains(
        "merge-base base-tip-sha HEAD"
    )
    assert_that(
        (Path(env["ARTIFACT_DIR"]) / "publication.json").read_text()
    ).is_equal_to(
        f"{int(collision)}\n",
    )
    assert_that((root / "partial-output").exists()).is_equal_to(not collision)


@pytest.mark.parametrize("collision", [False, True])
def test_real_artifact_cli_and_trusted_validation(
    git_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
    collision: bool,
) -> None:
    """Real CLI entrypoints exchange data without imports from another checkout."""
    import sys

    (git_tree / "NOTICE.md").write_text("changed")
    summary = git_tree.parent / f"{git_tree.name}-summary.md"
    summary.write_text("# Collision report\n" if collision else "# Bake summary\n")
    directory = git_tree.parent / f"{git_tree.name}-artifact"
    directory.mkdir()
    env = {
        "ARTIFACT_DIR": str(directory),
        "SUMMARY_PATH": str(summary),
        "SUMMARY_STATUS": str(int(collision)),
        "PR_HEAD_SHA": _head(git_tree),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    # Run stdlib entrypoints with the interpreter that launched pytest.
    for script, args in [
        ("vendor_pin_artifact.py", []),
        ("create_signed_commit.py", ["--validate-only"]),
    ]:
        result = subprocess.run(  # nosec B603 - fixed local Python scripts, no shell
            [sys.executable, str(_ROOT / "scripts/ci" / script), *args],
            cwd=git_tree,
            capture_output=True,
            text=True,
            check=False,
        )
        assert_that(result.returncode).described_as(result.stderr).is_zero()
    payload = vendor_pin_artifact.read_artifact(
        directory=directory,
        expected_head=_head(git_tree),
    )
    assert_that(payload["status"]).is_equal_to(int(collision))
    assert_that(bool(payload["fileChanges"]["additions"])).is_equal_to(not collision)
    assert_that((git_tree / "NOTICE.md").read_text()).is_equal_to("changed")


def test_collision_report_posts_without_commit_then_fails(
    git_tree: Path,
    api: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Collision publication leaves the head intact and marks the workflow red."""
    directory = _write_artifact(repo_root=git_tree, status=1)
    monkeypatch.chdir(git_tree)
    for name, value in {
        "ARTIFACT_DIR": str(directory),
        "PR_HEAD_SHA": _head(git_tree),
        "GITHUB_REPOSITORY": _REPOSITORY,
        "PR_BRANCH": _BRANCH,
        "PR_NUMBER": "522",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(create_signed_commit, "github_request", api)
    assert_that(create_signed_commit.main([])).is_equal_to(1)
    assert_that([call.kwargs["path"] for call in api.call_args_list]).does_not_contain(
        "/graphql"
    )
    assert_that(api.call_args.kwargs["path"]).ends_with("/issues/522/comments")


@pytest.mark.parametrize("branch", ["it's", 'embedded"quote', "both'\"quotes"])
@pytest.mark.parametrize("comment", ["", " # upstream default"])
@pytest.mark.parametrize("line_ending", ["\n", "\r\n", ""], ids=["lf", "crlf", "eof"])
def test_renovate_never_truncates_unsupported_branch_quotes(
    renovate_vendor_manager: dict[str, Any],
    branch: str,
    comment: str,
    line_ending: str,
) -> None:
    """Quoted branch names must never silently become a shorter upstream ref."""
    pattern = renovate_vendor_manager["matchStrings"][0].replace("(?<", "(?P<")
    for scalar in [branch, f"'{branch}'", json.dumps(branch)]:
        text = (
            f'repo: owner/example\n    sha: "{_NEW_HEAD}"\n'
            f"    branch: {scalar}{comment}{line_ending}"
        )
        assert_that(list(re.finditer(pattern, text))).is_empty()


@pytest.mark.parametrize(
    "branch_scalar",
    ["'main''suffix'", '"main"suffix"', "main'bad", '"main"#no-separation'],
)
@pytest.mark.parametrize("line_ending", ["\n", "\r\n", ""], ids=["lf", "crlf", "eof"])
def test_renovate_rejects_malformed_scalar_boundaries(
    renovate_vendor_manager: dict[str, Any],
    branch_scalar: str,
    line_ending: str,
) -> None:
    """Embedded quotes and unseparated comments cannot truncate the captured ref."""
    pattern = renovate_vendor_manager["matchStrings"][0].replace("(?<", "(?P<")
    text = (
        f'repo: owner/example\n    sha: "{_NEW_HEAD}"\n'
        f"    branch: {branch_scalar}{line_ending}"
    )
    assert_that(list(re.finditer(pattern, text))).is_empty()
