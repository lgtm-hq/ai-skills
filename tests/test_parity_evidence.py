"""Validate the draft host evidence contract without invoking live hosts."""

from __future__ import annotations

import calendar
import hashlib
import json
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
OWNER_DECISION = (
    "https://github.com/lgtm-hq/ai-skills/issues/563#issuecomment-6558530548"
)
CURSOR_DOCS = "https://cursor.com/docs/plugins#test-plugins-locally"
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
    paths = sorted(root.rglob("*.yaml"))
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
    """Keep the base Cartesian set separate from the IDE/policy dimensions."""
    identities = []
    for path, record in evidence_records:
        identity = (
            record["host"],
            record["interface"],
            record.get("policy", "unassessed"),
            *(record[key] for key in ("role", "scope", "mode")),
        )
        identities.append(identity)
        if record["interface"] == "cli":
            assert_that(path.parent.name).is_equal_to(record["host"])
        else:
            assert_that(path.parent.parts[-3:]).is_equal_to(
                ("cursor", "ide", record["policy"]),
            )
        assert_that(path.stem).is_equal_to(
            f"{record['role']}-{record['scope']}-{record['mode']}",
        )
    assert_that(identities).does_not_contain_duplicates()
    expected = {
        (host, "cli", "unassessed", role, scope, mode)
        for host, role, scope, mode in product(HOSTS, ROLES, SCOPES, MODES)
    } | {
        ("cursor", "ide", policy, role, scope, mode)
        for policy, role, scope, mode in product(
            ("none", "local-plugin-import-disabled"),
            ROLES,
            SCOPES,
            MODES,
        )
    }
    assert_that(set(identities)).is_equal_to(expected)


def test_evidence_field_types_and_vocabulary(
    evidence_records: list[tuple[Path, dict[str, Any]]],
) -> None:
    """Records use the complete draft field set and typed evidence steps."""
    for path, record in evidence_records:
        ide = record["interface"] == "ide"
        fields = FIELDS | {"policy", "evidence"} if ide else FIELDS
        assert_that(set(record)).described_as(str(path)).is_equal_to(fields)
        assert_that(record["state"]).is_in(*STATES)
        observations: tuple[str, ...] = ("invoked", "discovered", "absent")
        if ide:
            observations += ("not-measured",)
            evidence = record["evidence"]
            assert_that(set(evidence)).is_equal_to({"kind", "sources", "derivedFrom"})
            assert_that(evidence["kind"]).is_in(
                "pending",
                "measured",
                "owner-attestation",
                "owner-derived",
            )
            assert_that(evidence["sources"]).is_instance_of(list).is_not_empty()
            assert_that(evidence["derivedFrom"]).is_instance_of(list)
            for source in [*evidence["sources"], *evidence["derivedFrom"]]:
                assert_that(source).is_instance_of(str).is_not_empty()
            if record["observed"] == "not-measured":
                assert_that(record["state"]).is_in("unverified", "policy-blocked")
                assert_that(record["version"]).is_none()
                assert_that(record["os"]).is_none()
        assert_that(record["observed"]).is_in(*observations)
        if record["state"] == "partial":
            assert_that(record["observed"]).described_as(path.name).is_in(
                "invoked",
                "discovered",
            )
        assert_that(record["interface"]).is_in("cli", "ide")
        strings = (
            ("notes",)
            if ide and record["version"] is None
            else (
                "version",
                "os",
                "notes",
            )
        )
        for key in strings:
            assert_that(record[key]).is_instance_of(str).is_not_empty()
        for key in ("lostFields", "policyMarkers", "steps"):
            assert_that(record[key]).is_instance_of(list)
        for key in ("lostFields", "policyMarkers"):
            for value in record[key]:
                assert_that(value).is_instance_of(str).is_not_empty()
        assert_that(set(record["lostFields"])).is_subset_of(
            {"invocation", "activation", "permissions", "scope"},
        )
        if not ide or record["evidence"]["kind"] in {"pending", "measured"}:
            assert_that(record["steps"]).is_not_empty()
        for step in record["steps"]:
            step_fields = (
                {"phase", "action", "outcome", "output"}
                if ide
                else {
                    "phase",
                    "command",
                    "exitCode",
                    "output",
                }
            )
            assert_that(set(step)).is_equal_to(step_fields)
            assert_that(step["phase"]).is_in(
                "install",
                "reload",
                "invoke",
                "remove",
                "verify",
            )
            for key in ("action" if ide else "command", "output"):
                assert_that(step[key]).is_instance_of(str).is_not_empty()
            if ide:
                assert_that(step["outcome"]).is_in("pending", "observed", "not-run")
            else:
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
        ide = record["interface"] == "ide"
        if ide and record["evidence"]["kind"] == "owner-derived":
            # The owner-rule test below checks the source's full measured cycle.
            continue
        assert_that({step["phase"] for step in record["steps"]}).contains(
            "install",
            "reload",
            "invoke",
            "remove",
            "verify",
        )
        successful = {
            step["phase"]
            for step in record["steps"]
            if (step.get("outcome") == "observed" if ide else step["exitCode"] == 0)
        }
        assert_that(successful).contains("invoke", "remove", "verify")
        invocation_output = "\n".join(
            step["output"]
            for step in record["steps"]
            if step["phase"] == "invoke"
            and (step.get("outcome") == "observed" if ide else step["exitCode"] == 0)
        )
        assert_that(invocation_output).contains(f"PROBE-7f3a-{record['role']}")


def test_evidence_dates_and_unverified_reasons(
    evidence_records: list[tuple[Path, dict[str, Any]]],
) -> None:
    """Evidence expires within six calendar months and explains unknown cells."""
    for _, record in evidence_records:
        checked = date.fromisoformat(str(record["checkedOn"]))
        recheck = date.fromisoformat(str(record["recheckBy"]))
        assert_that(recheck).is_greater_than(checked)
        year = checked.year + (checked.month + 5) // 12
        month = (checked.month + 5) % 12 + 1
        maximum = date(
            year=year,
            month=month,
            day=min(checked.day, calendar.monthrange(year, month)[1]),
        )
        assert_that(recheck).is_less_than_or_equal_to(maximum)
        if record["state"] == "unverified":
            assert_that(record["notes"].lower()).contains("reason:")


def test_published_evidence_redaction(evidence_paths: list[Path]) -> None:
    """Scan records and prose for personal paths/secrets while permitting aliases."""
    root = evidence_paths[0].parents[2]
    paths = [*evidence_paths, *root.glob("*.md"), *root.rglob("raw/**/*.json")]
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


def test_raw_cursor_snapshots_match_write_once_digest_index() -> None:
    """Missing, changed or unindexed returned evidence must fail verification."""
    raw = Path(__file__).resolve().parents[1] / "docs/parity/evidence/cursor/raw"
    lines = (raw / "INDEX.sha256").read_text(encoding="utf-8").splitlines()
    assert_that(lines).is_not_empty()
    indexed = []
    for line in lines:
        digest, relative = line.split("  ", maxsplit=1)
        assert_that(re.fullmatch(r"[a-f0-9]{64}", digest)).is_not_none()
        path = raw / relative
        assert_that(path.resolve().is_relative_to(raw.resolve())).is_true()
        assert_that(path.is_file()).described_as(relative).is_true()
        assert_that(hashlib.sha256(path.read_bytes()).hexdigest()).described_as(
            relative,
        ).is_equal_to(digest)
        indexed.append(path)
    assert_that(indexed).does_not_contain_duplicates()
    assert_that(set(indexed)).is_equal_to(set(raw.rglob("*.json")))


def test_measured_cursor_cells_match_returned_checks(
    evidence_records: list[tuple[Path, dict[str, Any]]],
) -> None:
    """Measured cells cite actual checks, platform metadata and removal evidence."""
    root = Path(__file__).resolve().parents[1]
    for path, record in evidence_records:
        if record.get("evidence", {}).get("kind") != "measured":
            continue
        sources = record["evidence"]["sources"]
        raw_source = next(source for source in sources if ".json#" in source)
        relative, check_id = raw_source.split("#", maxsplit=1)
        run = json.loads((root / relative).read_text(encoding="utf-8"))
        checks = {check["check"]: check for check in run["checks"]}
        check = checks[check_id]
        for field in ("host", "interface", "version", "os", "checkedOn"):
            assert_that(record[field]).described_as(str(path)).is_equal_to(run[field])
        for field in ("role", "scope", "mode"):
            assert_that(record[field]).described_as(str(path)).is_equal_to(check[field])
        tag = check_id.split("-", maxsplit=1)[0]
        assert_that(checks[f"{tag}-removed"]["answer"]).is_equal_to("y")
        assert_that(checks["final-clean"]["answer"]).is_equal_to("y")
        if check["answer"] == "n":
            assert_that(record["state"]).is_equal_to("adapter-missing")
            assert_that(record["observed"]).is_equal_to("absent")
            assert_that(checks["npp-relaunch"]["answer"]).is_equal_to("n")
        elif check["answer"] == "d":
            assert_that(record["state"]).is_equal_to("partial")
            assert_that(record["observed"]).is_equal_to("discovered")
        else:
            assert_that(check["answer"]).is_equal_to("y")
            assert_that(record["observed"]).is_equal_to("invoked")
            if record["role"] == "lifecycle":
                assert_that(
                    any(
                        event.startswith(f"PROBE-7f3a-lifecycle-{tag} ")
                        for event in run["hookLog"]
                    ),
                ).is_true()
            elif record["role"] == "integration":
                assert_that(run["mcpLog"]).contains(f"{tag} called")
        if check_id == "ue-skill":
            assert_that(record["state"]).is_equal_to("partial")
            assert_that(record["lostFields"]).contains("invocation")
            assert_that(record["notes"]).contains("unconfirmed", "file search")


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


def test_cursor_policy_claims_follow_answered_owner_rule(
    evidence_records: list[tuple[Path, dict[str, Any]]],
) -> None:
    """Owner definitions and file derivations cannot masquerade as measurements."""
    by_path = {path.resolve(): record for path, record in evidence_records}
    root = Path(__file__).resolve().parents[1]
    for path, record in evidence_records:
        if record["host"] != "cursor":
            continue
        if record["interface"] == "cli":
            assert_that(record["state"]).is_equal_to("unverified")
            assert_that(record["policyMarkers"]).is_empty()
            continue
        evidence = record["evidence"]
        if record["policy"] == "none":
            assert_that(evidence["kind"]).is_in("pending", "measured")
            assert_that(record["policyMarkers"]).is_empty()
            assert_that(evidence["derivedFrom"]).is_empty()
            if evidence["kind"] == "pending":
                assert_that(record["state"]).is_equal_to("unverified")
                assert_that(record["observed"]).is_equal_to("not-measured")
            else:
                assert_that(record["version"]).is_instance_of(str).is_not_empty()
                assert_that(record["os"]).starts_with("darwin-")
                assert_that(record["observed"]).is_not_equal_to("not-measured")
                assert_that(
                    any(".json#" in source for source in evidence["sources"])
                ).is_true()
            continue
        assert_that(record["policyMarkers"]).is_equal_to(["Allow Local Plugin Imports"])
        assert_that(evidence["sources"]).contains(OWNER_DECISION)
        assert_that(record["steps"]).is_empty()
        if record["mode"] == "native-plugin":
            assert_that(record["state"]).is_equal_to("policy-blocked")
            assert_that(record["observed"]).is_equal_to("not-measured")
            assert_that(evidence["kind"]).is_equal_to("owner-attestation")
            assert_that(evidence["sources"]).contains(CURSOR_DOCS)
            assert_that(evidence["derivedFrom"]).is_empty()
        else:
            assert_that(evidence["kind"]).is_equal_to("owner-derived")
            source_path = path.parent.parent / "none" / path.name
            assert_that(evidence["derivedFrom"]).is_equal_to(
                [source_path.relative_to(root).as_posix()],
            )
            source = by_path[source_path.resolve()]
            for field in ("state", "observed", "version", "os", "lostFields"):
                assert_that(record[field]).described_as(str(path)).is_equal_to(
                    source[field],
                )
            if source["state"] == "supported":
                assert_that(source["evidence"]["kind"]).is_equal_to("measured")
            if source["evidence"]["kind"] == "pending":
                tag = {
                    ("user", "user-explode"): "ue",
                    ("project", "repo-materialize"): "rm",
                }.get(
                    (record["scope"], record["mode"]),
                )
                dependency = (
                    f"cursor-probe-results-*.json check {tag}-{record['role']}"
                    if tag
                    else "undefined mode/scope pair under #581"
                )
                assert_that(" ".join(record["notes"].split())).contains(dependency)
                assert_that(" ".join(source["notes"].split())).contains(dependency)


@pytest.mark.parametrize("sources", [["synthetic.json#ue-skill"], ["public-docs-only"]])
def test_measured_cursor_record_requires_returned_json_source(
    sources: list[str],
) -> None:
    """Exercise measured-record validation without publishing fake evidence."""
    record = {
        "host": "cursor",
        "interface": "ide",
        "policy": "none",
        "policyMarkers": [],
        "evidence": {"kind": "measured", "derivedFrom": [], "sources": sources},
        "version": "synthetic-version",
        "os": "darwin-synthetic",
        "observed": "synthetic-observation",
    }
    records = [(Path("synthetic.json"), record)]
    if sources == ["public-docs-only"]:
        with pytest.raises(AssertionError):
            test_cursor_policy_claims_follow_answered_owner_rule(records)
    else:
        test_cursor_policy_claims_follow_answered_owner_rule(records)
