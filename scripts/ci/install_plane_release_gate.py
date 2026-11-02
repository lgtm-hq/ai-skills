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

QUEUE_ALLOWANCE_SECONDS = 30 * 60
# changes (5), native matrix (40), offline-linux (15), final gate (5), plus
# 30 minutes total for runner queues/concurrency. The job allows setup overhead.
DEFAULT_TIMEOUT_SECONDS = 95 * 60
MAX_READ_FAILURES = 3


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
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
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
    failures = 0
    first = True
    while first or time.monotonic() < deadline:
        first = False
        try:
            response = subprocess.run(  # nosec B603 B607 - fixed read-only gh API argv
                args=["gh", "api", "--paginate", "--slurp", endpoint],
                check=True,
                capture_output=True,
                text=True,
                # Zero is a single snapshot with no polling, not a 100ms API
                # deadline. Timed polls remain bounded by their total budget.
                timeout=(
                    60
                    if args.timeout <= 0
                    else min(60, max(0.1, deadline - time.monotonic()))
                ),
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            failures += 1
            transient = isinstance(error, subprocess.TimeoutExpired) or bool(
                re.search(
                    r"HTTP (?:429|5\d\d)\b|connection reset|TLS handshake timeout|"
                    r"temporary failure|i/o timeout|unexpected EOF",
                    str(error.stderr or ""),
                    flags=re.IGNORECASE,
                )
            )
            if not transient or failures >= MAX_READ_FAILURES:
                print(f"Mandatory harness API read failed ({failures} attempts)")
                return 1
            print(
                f"Transient harness API read failure ({failures}/{MAX_READ_FAILURES})"
            )
            result = "pending"
        else:
            failures = 0
            result = latest_result(
                json.loads(response.stdout), head, event_name, branch
            )
            if args.timeout > 0 and time.monotonic() > deadline:
                result = "expired"
        if result != "pending" or time.monotonic() >= deadline:
            print(f"Mandatory install-plane harness on {head}: {result}")
            return 0 if result == "success" else 1
        delay = min(args.interval, 5) if failures else args.interval
        time.sleep(min(max(0.1, delay), max(0, deadline - time.monotonic())))
    print(f"Mandatory install-plane harness on {head}: deadline expired")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
