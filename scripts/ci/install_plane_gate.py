#!/usr/bin/env python3
"""Fail closed when a required native/offline harness job did not succeed."""

import json
import os


def gate(needs: dict[str, dict[str, object]]) -> bool:
    """Allow a deliberate no-input skip only after a successful change detector."""
    if needs["changes"]["result"] != "success":
        return False
    results = [needs[name]["result"] for name in ("native", "offline-linux")]
    if all(result == "success" for result in results):
        return True
    return bool(
        os.environ.get("SPIKE_MANDATORY") != "true"
        and needs["changes"]["outputs"] == {"changed": "false"}
        and all(result == "skipped" for result in results)
    )


if __name__ == "__main__":
    raise SystemExit(0 if gate(json.loads(os.environ["SPIKE_JOB_RESULTS"])) else 1)
