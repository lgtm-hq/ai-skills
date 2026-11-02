#!/usr/bin/env python3
"""Require a successful spike workflow on the exact release or queue head."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess  # nosec B404 - read-only GitHub API, fixed workflow endpoint
import time
from pathlib import Path
from typing import Any


def required_head(event: dict[str, Any], event_name: str) -> str | None:
    """Return the mandatory immutable head; ordinary PRs need no extra run."""
    if event_name == "merge_group":
        head = event["merge_group"]["head_sha"]
    elif event_name == "pull_request" and event["pull_request"]["head"][
        "ref"
    ].startswith("release/"):
        head = event["pull_request"]["head"]["sha"]
    else:
        return None
    if not isinstance(head, str) or not re.fullmatch(r"[a-f0-9]{40}", head):
        raise ValueError("expected exact release/queue head SHA")
    return head


def latest_result(
    pages: list[dict[str, Any]], head: str, event_name: str, branch: str | None = None
) -> str:
    """Reject absent, stale, skipped or failed runs, including failed reruns."""
    runs = [
        run
        for page in pages
        for run in page["workflow_runs"]
        if run["head_sha"] == head
        and run["event"] == event_name
        and (branch is None or run.get("head_branch") == branch)
    ]
    if not runs:
        return "pending"
    latest = max(runs, key=lambda run: (run["id"], run.get("run_attempt", 1)))
    if latest["status"] != "completed":
        return "pending"
    return "success" if latest["conclusion"] == "success" else "failure"


def main() -> int:
    """Poll the read-only Actions API with a bounded deadline and fail closed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=3000)
    parser.add_argument("--interval", type=float, default=15)
    args = parser.parse_args()
    event_name = os.environ["GITHUB_EVENT_NAME"]
    event = json.loads(
        Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
    )
    head = required_head(event, event_name)
    if head is None:
        print("No mandatory release/queue harness run for this event")
        return 0
    repository = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository")
    endpoint = (
        f"repos/{repository}/actions/workflows/install-plane-spike.yml/runs"
        f"?head_sha={head}&event={event_name}&per_page=100"
    )
    deadline = time.monotonic() + max(0, args.timeout)
    branch = (
        event["pull_request"]["head"]["ref"] if event_name == "pull_request" else None
    )
    while True:
        response = subprocess.run(  # nosec B603 B607 - fixed read-only gh API argv
            args=["gh", "api", "--paginate", "--slurp", endpoint],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        result = latest_result(json.loads(response.stdout), head, event_name, branch)
        if result != "pending" or time.monotonic() >= deadline:
            print(f"Mandatory install-plane harness on {head}: {result}")
            return 0 if result == "success" else 1
        time.sleep(min(max(0.1, args.interval), max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    raise SystemExit(main())
