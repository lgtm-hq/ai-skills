"""Validate the draft host evidence contract without invoking live hosts."""

from __future__ import annotations

import re
from datetime import date
from itertools import product
from pathlib import Path
from typing import Any

import pytest
import yaml
from assertpy import assert_that

HOSTS = ("claude-code", "codex", "cursor")
ROLES = ("skill", "instruction", "specialist", "workflow", "lifecycle", "integration")
SCOPES = ("user", "project")
MODES = ("native-plugin", "user-explode", "repo-materialize")
STATES = (
    "supported",
    "partial",
    "unverified",
    "platform-unavailable",
    "policy-blocked",
    "source-unportable",
    "adapter-missing",
)
FIELDS = {
    "host",
    "interface",
    "version",
    "os",
    "role",
    "scope",
    "mode",
    "state",
    "lostFields",
    "observed",
    "policyMarkers",
    "checkedOn",
    "recheckBy",
    "steps",
    "notes",
}


@pytest.fixture
def evidence_paths() -> list[Path]:
    """Find every cell record in the draft parity directory.

    Returns:
        Sorted YAML evidence paths.
    """
    root = Path(__file__).resolve().parents[1] / "docs/parity/evidence"
    paths = sorted(root.glob("*/*.yaml"))
    assert_that(paths).is_not_empty()
    return paths


@pytest.fixture
def evidence_records(evidence_paths: list[Path]) -> list[tuple[Path, dict[str, Any]]]:
    """Load evidence with safe YAML parsing.

    Args:
        evidence_paths: Record paths supplied by the discovery fixture.

    Returns:
        Source paths paired with parsed mappings.
    """
    records = []
    for path in evidence_paths:
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert_that(record).described_as(str(path)).is_instance_of(dict)
        records.append((path, record))
    return records


def test_evidence_covers_every_cell_once(
    evidence_records: list[tuple[Path, dict[str, Any]]],
) -> None:
    """All 108 cells exist once, with filenames matching their identity."""
    identities = []
    for path, record in evidence_records:
        identity = tuple(record[key] for key in ("host", "role", "scope", "mode"))
        identities.append(identity)
        assert_that(path.parent.name).is_equal_to(record["host"])
        assert_that(path.stem).is_equal_to(
            f"{record['role']}-{record['scope']}-{record['mode']}",
        )
    assert_that(identities).does_not_contain_duplicates()
    assert_that(set(identities)).is_equal_to(set(product(HOSTS, ROLES, SCOPES, MODES)))


def test_evidence_field_types_and_vocabulary(
    evidence_records: list[tuple[Path, dict[str, Any]]],
) -> None:
    """Records use the complete draft field set and typed evidence steps."""
    for path, record in evidence_records:
        assert_that(set(record)).described_as(path.name).is_equal_to(FIELDS)
        assert_that(record["state"]).is_in(*STATES)
        assert_that(record["observed"]).is_in("invoked", "discovered", "absent")
        assert_that(record["interface"]).is_equal_to("cli")
        for key in ("version", "os", "notes"):
            assert_that(record[key]).is_instance_of(str).is_not_empty()
        for key in ("lostFields", "policyMarkers", "steps"):
            assert_that(record[key]).is_instance_of(list)
        for key in ("lostFields", "policyMarkers"):
            for value in record[key]:
                assert_that(value).is_instance_of(str).is_not_empty()
        assert_that(set(record["lostFields"])).is_subset_of(
            {"invocation", "activation", "permissions", "scope"},
        )
        assert_that(record["steps"]).is_not_empty()
        for step in record["steps"]:
            assert_that(set(step)).is_equal_to(
                {"phase", "command", "exitCode", "output"},
            )
            assert_that(step["phase"]).is_in(
                "install",
                "reload",
                "invoke",
                "remove",
                "verify",
            )
            for key in ("command", "output"):
                assert_that(step[key]).is_instance_of(str).is_not_empty()
            assert_that(type(step["exitCode"])).is_in(int, type(None))
            if step["exitCode"] is None:
                assert_that(record["state"]).is_equal_to("unverified")


def test_supported_requires_invocation_and_complete_cycle(
    evidence_records: list[tuple[Path, dict[str, Any]]],
) -> None:
    """A supported claim has successful invocation and removal evidence."""
    for path, record in evidence_records:
        if record["state"] != "supported":
            continue
        assert_that(record["observed"]).described_as(path.name).is_equal_to("invoked")
        assert_that(record["lostFields"]).is_empty()
        assert_that({step["phase"] for step in record["steps"]}).contains(
            "install",
            "reload",
            "invoke",
            "remove",
            "verify",
        )
        successful = {
            step["phase"] for step in record["steps"] if step["exitCode"] == 0
        }
        assert_that(successful).contains("invoke", "remove", "verify")
        invocation_output = "\n".join(
            step["output"]
            for step in record["steps"]
            if step["phase"] == "invoke" and step["exitCode"] == 0
        )
        assert_that(invocation_output).contains(f"PROBE-7f3a-{record['role']}")


def test_evidence_dates_and_redaction(
    evidence_records: list[tuple[Path, dict[str, Any]]],
) -> None:
    """Evidence has a forward recheck date and no personal absolute paths."""
    home_path = re.compile(r"(?:/home/|/Users/|[A-Za-z]:[\\/]Users[\\/])[^\s]+")
    for path, record in evidence_records:
        checked = date.fromisoformat(str(record["checkedOn"]))
        recheck = date.fromisoformat(str(record["recheckBy"]))
        assert_that(recheck).is_greater_than(checked)
        assert_that(home_path.search(path.read_text(encoding="utf-8"))).is_none()
        if record["state"] == "unverified":
            assert_that(record["notes"].lower()).contains("reason:")


def test_cursor_policy_claims_require_machine_evidence(
    evidence_records: list[tuple[Path, dict[str, Any]]],
) -> None:
    """The laptop cannot silently stand in for the required policy machine."""
    for _, record in evidence_records:
        if record["host"] == "cursor" and record["state"] != "unverified":
            assert_that(record["policyMarkers"]).is_not_empty()
            assert_that(record["notes"]).contains("policy machine")
