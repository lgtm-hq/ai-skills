"""Validate the draft host evidence contract without invoking live hosts."""

from __future__ import annotations

import re
import shlex
from collections import Counter
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
        if record["state"] == "partial":
            assert_that(record["observed"]).described_as(path.name).is_in(
                "invoked",
                "discovered",
            )
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


def test_evidence_dates_and_unverified_reasons(
    evidence_records: list[tuple[Path, dict[str, Any]]],
) -> None:
    """Evidence has a forward recheck date and explains unverified states."""
    for _, record in evidence_records:
        checked = date.fromisoformat(str(record["checkedOn"]))
        recheck = date.fromisoformat(str(record["recheckBy"]))
        assert_that(recheck).is_greater_than(checked)
        if record["state"] == "unverified":
            assert_that(record["notes"].lower()).contains("reason:")


def test_published_evidence_redaction(evidence_paths: list[Path]) -> None:
    """Scan records and prose for personal paths/secrets while permitting aliases."""
    root = evidence_paths[0].parents[2]
    paths = [*evidence_paths, *root.glob("*.md")]
    home_path = re.compile(
        r"(?<![\w~/])(?:/home/|/Users/|[A-Za-z]:[\\/]Users[\\/])[^\s]+",
    )
    secret = re.compile(
        r"(?:\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}"
        r"|\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}"
        r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert_that(home_path.search(text)).described_as(str(path)).is_none()
        assert_that(secret.search(text)).described_as(str(path)).is_none()


def test_recorded_attempt_totals(evidence_paths: list[Path]) -> None:
    """Count process attempts and exclude CLI help from model-attempt totals."""
    root = evidence_paths[0].parents[2]
    log = (root / "probe-log.md").read_text(encoding="utf-8")
    attempts = re.findall(
        r"^### (R\d{3}): [^\n]+ \(exit ([^)]+)\)\n\n```text\n(.*?)\n```",
        log,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert_that([ref for ref, _, _ in attempts]).is_equal_to(
        [f"R{number:03d}" for number in range(1, 113)],
    )
    commands = {ref: shlex.split(command) for ref, _, command in attempts}
    model_attempts: dict[str, list[str]] = {"Codex": [], "Claude": [], "Cursor": []}
    for ref, argv in commands.items():
        if any(flag in argv for flag in ("--help", "-h", "help")):
            continue
        if argv[:2] == ["codex", "exec"]:
            model_attempts["Codex"].append(ref)
        elif argv[0] == "claude" and "-p" in argv:
            model_attempts["Claude"].append(ref)
        elif argv[0] == "cursor-agent" and "-p" in argv:
            model_attempts["Cursor"].append(ref)
    assert_that(commands["R009"]).is_equal_to(["codex", "exec", "--help"])
    assert_that(model_attempts["Codex"]).does_not_contain("R009").is_length(10)
    assert_that(model_attempts["Claude"]).is_length(6)
    assert_that(model_attempts["Cursor"]).is_length(1)
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert_that(readme).contains("Model attempts: 10 Codex, six Claude, one Cursor")
    exits = Counter(exit_code for _, exit_code, _ in attempts)
    assert_that(exits["0"]).is_equal_to(100)
    assert_that(exits["1"]).is_equal_to(7)
    assert_that(exits["2"]).is_equal_to(1)
    assert_that(exits["124"]).is_equal_to(1)
    assert_that(exits["not captured; RPC succeeded"]).is_equal_to(3)


def test_cursor_policy_claims_require_machine_evidence(
    evidence_records: list[tuple[Path, dict[str, Any]]],
) -> None:
    """The laptop cannot silently stand in for the required policy machine."""
    for _, record in evidence_records:
        if record["host"] == "cursor" and record["state"] != "unverified":
            assert_that(record["policyMarkers"]).is_not_empty()
            assert_that(record["notes"]).contains("policy machine")
