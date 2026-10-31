#!/usr/bin/env python3
"""Publish generated vendor data as a GitHub-signed App commit and PR comment."""

from __future__ import annotations

import base64
import http.client
import json
import os
import ssl
import subprocess  # nosec B404 - fixed git argv, no shell
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

RequestJson = Callable[..., Any]
_MARKER = "<!-- vendor-pin-regen -->"
_BOT_LOGIN = "lgtm-release-bot[bot]"
_GENERATED_FILES = frozenset({"NOTICE.md", "npm/ai-skills/NOTICE.md"})
_GENERATED_DIRS = ("vendor-indexes/", "npm/ai-skills/data/")
_MUTATION = """
mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { oid } }
}
"""


def _git(*, repo_root: Path, args: list[str]) -> bytes:
    """Read local Git state without modifying the index or branch.

    Args:
        repo_root: Checkout root.
        args: Git subcommand and arguments.

    Returns:
        Raw stdout, preserving NUL-delimited paths.
    """
    return subprocess.check_output(  # nosec B603 B607 - fixed git executable
        ["git", *args],
        cwd=repo_root,
    )


def file_changes(*, repo_root: Path) -> dict[str, list[dict[str, str]]]:
    """Encode tracked changes and new generated files for GraphQL.

    Args:
        repo_root: Checkout containing regenerated files.

    Returns:
        Base64 additions and path-only deletions, including renamed files.

    Raises:
        ValueError: If a change is outside the catalog or traverses a symlink.
    """
    paths: set[str] = set()
    for args in (
        ["diff", "--name-only", "--no-renames", "-z", "HEAD", "--"],
        ["ls-files", "--others", "--exclude-standard", "-z"],
    ):
        paths.update(
            path
            for path in _git(repo_root=repo_root, args=args).decode().split("\0")
            if path
        )
    changes: dict[str, list[dict[str, str]]] = {"additions": [], "deletions": []}
    for name in sorted(paths):
        if name not in _GENERATED_FILES and not name.startswith(_GENERATED_DIRS):
            msg = f"Refusing to commit a non-generated path: {name}"
            raise ValueError(msg)
        path = repo_root / name
        if any(item.is_symlink() for item in (path, *path.parents)):
            msg = f"Refusing to commit a symlink: {name}"
            raise ValueError(msg)
        if path.is_file():
            changes["additions"].append(
                {
                    "path": name,
                    "contents": base64.b64encode(path.read_bytes()).decode(),
                },
            )
        elif not path.exists():
            changes["deletions"].append({"path": name})
        else:
            msg = f"Expected a generated regular file: {name}"
            raise ValueError(msg)
    return changes


def github_request(
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    """Call GitHub with the short-lived App token, never a fallback token.

    Args:
        method: HTTP method.
        path: GitHub API path.
        payload: Optional JSON request body.

    Returns:
        Parsed JSON response.

    Raises:
        RuntimeError: If GitHub rejects the request.
    """
    # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected - Python >=3.13 with certificate verification
    connection = http.client.HTTPSConnection(
        host="api.github.com",
        timeout=60,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            method=method,
            url=path,
            body=json.dumps(payload) if payload is not None else None,
            headers={
                "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "lgtm-hq-vendor-pin-regen",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response = connection.getresponse()
        content = response.read()
        if not 200 <= response.status < 300:
            msg = f"GitHub {method} {path} failed (HTTP {response.status})"
            raise RuntimeError(msg)
        return json.loads(content)
    finally:
        connection.close()


def upsert_summary(
    *,
    repository: str,
    pr_number: int,
    summary: str,
    request: RequestJson,
) -> None:
    """Create or update the release bot's one sticky summary comment.

    Args:
        repository: Owner/repo slug.
        pr_number: Pull request number.
        summary: Markdown bake delta.
        request: Injectable JSON HTTP client.
    """
    body = f"{_MARKER}\n{summary}"
    collection = f"/repos/{repository}/issues/{pr_number}/comments"
    page = 1
    while True:
        comments = request(method="GET", path=f"{collection}?per_page=100&page={page}")
        for comment in comments:
            if comment["user"]["login"] == _BOT_LOGIN and comment["body"].startswith(
                _MARKER
            ):
                if comment["body"] != body:
                    request(
                        method="PATCH",
                        path=f"/repos/{repository}/issues/comments/{comment['id']}",
                        payload={"body": body},
                    )
                return
        if len(comments) < 100:
            break
        page += 1
    request(method="POST", path=collection, payload={"body": body})


def publish(
    *,
    repo_root: Path,
    repository: str,
    branch: str,
    expected_head: str,
    pr_number: int,
    summary: str,
    request: RequestJson,
) -> str:
    """Sign generated changes through GitHub and publish the bake summary.

    Args:
        repo_root: Regenerated checkout of the exact PR head.
        repository: Owner/repo slug.
        branch: Same-repository Renovate head branch.
        expected_head: PR event head SHA, used as the API compare-and-swap guard.
        pr_number: Pull request number.
        summary: Markdown bake delta.
        request: Injectable JSON HTTP client.

    Returns:
        New commit OID, or the unchanged head when no generated files differ.

    Raises:
        ValueError: If the checkout or remote PR no longer matches the event.
        RuntimeError: If GraphQL rejects the commit, including a head race.
    """
    local_head = _git(repo_root=repo_root, args=["rev-parse", "HEAD"]).decode().strip()
    if local_head != expected_head or not branch.startswith("renovate/"):
        msg = "Checkout must match the expected Renovate PR head"
        raise ValueError(msg)
    pr = request(method="GET", path=f"/repos/{repository}/pulls/{pr_number}")
    if (
        pr["state"] != "open"
        or pr["head"]["sha"] != expected_head
        or pr["head"]["ref"] != branch
        or pr["head"]["repo"]["full_name"] != repository
    ):
        msg = "PR head has changed or is not an open same-repository PR"
        raise ValueError(msg)
    changes = file_changes(repo_root=repo_root)
    oid = expected_head
    if any(changes.values()):
        result = request(
            method="POST",
            path="/graphql",
            payload={
                "query": _MUTATION,
                "variables": {
                    "input": {
                        "branch": {
                            "repositoryNameWithOwner": repository,
                            "branchName": branch,
                        },
                        "expectedHeadOid": expected_head,
                        "message": {
                            "headline": (
                                "chore(vendors): regenerate pinned vendor catalog"
                            ),
                        },
                        "fileChanges": changes,
                    },
                },
            },
        )
        if result.get("errors") or not (result.get("data") or {}).get(
            "createCommitOnBranch",
        ):
            msg = "GitHub rejected createCommitOnBranch; no retry against a newer head"
            raise RuntimeError(msg)
        oid = result["data"]["createCommitOnBranch"]["commit"]["oid"]
    upsert_summary(
        repository=repository,
        pr_number=pr_number,
        summary=summary,
        request=request,
    )
    return str(oid)


def main() -> int:
    """Publish using workflow-provided inputs, failing closed on API errors.

    Returns:
        Zero on success, one on failure or unresolved summary collisions.
    """
    try:
        oid = publish(
            repo_root=Path.cwd(),
            repository=os.environ["GITHUB_REPOSITORY"],
            branch=os.environ["PR_BRANCH"],
            expected_head=os.environ["PR_HEAD_SHA"],
            pr_number=int(os.environ["PR_NUMBER"]),
            summary=Path(os.environ["SUMMARY_PATH"]).read_text(encoding="utf-8"),
            request=github_request,
        )
        print(f"Vendor catalog head: {oid}")
        return int(os.environ.get("SUMMARY_STATUS", "0") != "0")
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        http.client.HTTPException,
        subprocess.CalledProcessError,
    ) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
