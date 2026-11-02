#!/usr/bin/env python3
"""Retain unverified acquisition/upload outcomes using runner stdlib only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def append_summary(text: str) -> None:
    """Append evidence when the runner provides a job summary path."""
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(path).open("a", encoding="utf-8", newline="\n") as summary:
            summary.write(text)


def retain_acquisition() -> None:
    """Export acquisition outcomes without asserting source or scenario identity."""
    env = os.environ
    result = {
        "status": "unverified",
        "collection_scope": "hosted acquisition outcomes only",
        "source_head": None,
        "expected_source_head": env.get("SPIKE_SOURCE_SHA"),
        "workflow_event": env.get("GITHUB_EVENT_NAME"),
        "workflow_run_id": env.get("GITHUB_RUN_ID"),
        "workflow_run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
        "acquisition": {
            key: env.get(key)
            for key in (
                "SPIKE_HARDEN_OUTCOME",
                "SPIKE_CHECKOUT_OUTCOME",
                "SPIKE_HELPER_CHECKOUT_OUTCOME",
                "SPIKE_DOWNLOAD_OUTCOME",
                "SPIKE_UNPACK_OUTCOME",
                "SPIKE_MEASURE_OUTCOME",
            )
        },
        "probe_denial_proven": False,
        "installer_denial_proven": False,
        "reason": "No same-host unrestricted control or payload provenance; "
        "this acquisition-only record does not assess separately retained scenarios",
    }
    raw = json.dumps(result, indent=2) + "\n"
    print(raw, flush=True)
    append_summary("\n### Acquisition (unverified)\n```json\n" + raw + "```\n")
    path = Path("build/spike/results/acquisition.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8", newline="\n")


def main() -> None:
    """Report acquisition or final artifact upload, without fetching anything."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("acquisition", "upload"))
    if parser.parse_args().phase == "acquisition":
        retain_acquisition()
    else:
        outcome = os.environ.get("SPIKE_UPLOAD_OUTCOME", "unknown")
        message = (
            f"Artifact upload outcome: {outcome}; acquisition remains unverified.\n"
        )
        print(message, end="", flush=True)
        append_summary(message)


if __name__ == "__main__":
    main()
