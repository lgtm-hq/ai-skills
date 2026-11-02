"""Exercise mandatory release-head and fail-closed harness gates without network."""

import json
import os
import subprocess  # nosec B404 - local gate scripts and synthetic gh only
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from assertpy import assert_that
from ci import install_plane_release_gate as release_gate
from ci.install_plane_gate import gate
from ci.install_plane_release_gate import latest_result, required_head

HEAD = "a" * 40


def test_release_timeout_covers_actual_sequential_workflow() -> None:
    """The poll and runner budget cover every sequential job plus queue delays."""
    workflows = Path(__file__).resolve().parents[1] / ".github/workflows"
    spike = yaml.safe_load((workflows / "install-plane-spike.yml").read_text())
    release = yaml.safe_load((workflows / "install-plane-release-gate.yml").read_text())
    # The matrix runs in parallel, but these four stages run sequentially.
    seconds = sum(
        spike["jobs"][name]["timeout-minutes"] * 60
        for name in ("changes", "native", "offline-linux", "gate")
    )
    assert_that(release_gate.DEFAULT_TIMEOUT_SECONDS).is_greater_than_or_equal_to(
        seconds + release_gate.QUEUE_ALLOWANCE_SECONDS
    )
    assert_that(
        release["jobs"]["release-spike"]["timeout-minutes"] * 60
    ).is_greater_than_or_equal_to(release_gate.DEFAULT_TIMEOUT_SECONDS + 5 * 60)


@pytest.fixture
def release_gate_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a release event and a short deterministic polling budget."""
    event = tmp_path / "release.json"
    event.write_text(
        json.dumps({"pull_request": {"head": {"ref": "release/v1", "sha": HEAD}}})
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")
    monkeypatch.setattr(sys, "argv", ["gate", "--timeout", "30", "--interval", "15"])


@pytest.mark.parametrize(
    ("responses", "expected", "calls"),
    [
        (["pending", "success"], 0, 2),
        (["pending", "pending", "success"], 1, 2),
        (["transient", "success"], 0, 2),
        (["transient", "pending", "transient", "success"], 0, 4),
        (["timeout", "success"], 0, 2),
        (["transient", "transient", "transient", "success"], 1, 3),
        (["forbidden", "success"], 1, 1),
        (["failure", "success"], 1, 1),
        (["skipped", "success"], 1, 1),
    ],
)
def test_release_poll_deadline_and_read_error_controls(
    release_gate_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    responses: list[str],
    expected: int,
    calls: int,
) -> None:
    """Exercise main with a virtual clock, bounded retries and exact-head evidence."""
    clock = [0.0]
    requests: list[list[str]] = []

    def sleep(seconds: float) -> None:
        """Advance time without sleeping or making network requests."""
        clock[0] += seconds

    def api(**kwargs: Any) -> SimpleNamespace:
        """Return synthetic read-only API observations at the subprocess boundary."""
        requests.append(kwargs["args"])
        response = responses[len(requests) - 1]
        if response == "timeout":
            raise subprocess.TimeoutExpired(cmd="gh", timeout=1)
        if response in {"transient", "forbidden"}:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd="gh",
                stderr="HTTP 503" if response == "transient" else "HTTP 403",
            )
        run = {
            "id": 1,
            "head_sha": HEAD,
            "event": "pull_request",
            "head_branch": "release/v1",
            "status": "in_progress" if response == "pending" else "completed",
            "conclusion": response,
        }
        return SimpleNamespace(stdout=json.dumps([{"workflow_runs": [run]}]))

    monkeypatch.setattr(release_gate.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(release_gate.time, "sleep", sleep)
    monkeypatch.setattr(release_gate.subprocess, "run", api)
    assert_that(release_gate.main()).is_equal_to(expected)
    assert_that(requests).is_length(calls)
    assert_that(clock[0]).is_less_than_or_equal_to(30)
    assert_that(
        all(argv[:4] == ["gh", "api", "--paginate", "--slurp"] for argv in requests)
    ).is_true()


@pytest.mark.parametrize(("elapsed", "expected"), [(29.999, 0), (30, 0), (30.001, 1)])
def test_release_poll_checks_response_at_deadline(
    release_gate_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    elapsed: float,
    expected: int,
) -> None:
    """A read may consume the remaining budget; a late result cannot pass."""
    clock = [0.0]

    def api(**kwargs: Any) -> SimpleNamespace:
        """Model a read completing just before, on, or after the deadline."""
        assert_that(kwargs["timeout"]).is_equal_to(30)
        clock[0] = elapsed
        run = {
            "id": 1,
            "head_sha": HEAD,
            "event": "pull_request",
            "head_branch": "release/v1",
            "status": "completed",
            "conclusion": "success",
        }
        return SimpleNamespace(stdout=json.dumps([{"workflow_runs": [run]}]))

    monkeypatch.setattr(release_gate.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(release_gate.subprocess, "run", api)
    assert_that(release_gate.main()).is_equal_to(expected)


def test_release_snapshot_retains_bounded_api_read(
    release_gate_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No-poll mode still permits one normal API read and never sleeps or retries."""
    monkeypatch.setattr(sys, "argv", ["gate", "--timeout", "0"])
    requests: list[float] = []

    def api(**kwargs: Any) -> SimpleNamespace:
        """Return no current-head run after recording the one-shot read bound."""
        requests.append(kwargs["timeout"])
        return SimpleNamespace(stdout=json.dumps([{"workflow_runs": []}]))

    monkeypatch.setattr(release_gate.subprocess, "run", api)
    assert_that(release_gate.main()).is_equal_to(1)
    assert_that(requests).contains_only(60)


@pytest.mark.parametrize("branch", ["release/v1", "fix/example"])
def test_required_head_uses_release_pr_identity(branch: str) -> None:
    """Only release PRs require this additional exact-head run."""
    event = {"pull_request": {"head": {"ref": branch, "sha": HEAD}}}
    assert_that(required_head(event, "pull_request")).is_equal_to(
        HEAD if branch.startswith("release/") else None
    )
    assert_that(
        required_head({"merge_group": {"head_sha": HEAD}}, "merge_group")
    ).is_equal_to(HEAD)


@pytest.mark.parametrize(
    "conclusion", ["success", "failure", "skipped", "cancelled", None]
)
def test_release_gate_runs_at_real_cli_boundary(
    tmp_path: Path, conclusion: str | None
) -> None:
    """A fake API returns current-head evidence; stale success never rescues it."""
    run = {
        "id": 2,
        "head_sha": HEAD,
        "head_branch": "release/v1",
        "event": "pull_request",
        "status": "completed",
        "conclusion": conclusion,
    }
    pages = [
        {
            "workflow_runs": [
                {**run, "id": 1, "head_sha": "b" * 40, "conclusion": "success"},
                run,
            ]
        }
    ]
    fake = tmp_path / "gh"
    fake.write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        "if sys.argv[1:5] != ['api', '--paginate', '--slurp', "
        "'repos/example/repo/actions/workflows/install-plane-spike.yml/runs"
        f"?head_sha={HEAD}&event=pull_request&per_page=100']:\n"
        "    raise RuntimeError('unexpected API argv')\n"
        f"print({json.dumps(pages)!r})\n",
        encoding="utf-8",
    )
    fake.chmod(0o700)
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"pull_request": {"head": {"ref": "release/v1", "sha": HEAD}}})
    )
    script = (
        Path(__file__).resolve().parents[1] / "scripts/ci/install_plane_release_gate.py"
    )
    result = (
        subprocess.run(  # nosec B603 - local script, fake read-only API, no network
            args=[sys.executable, str(script), "--timeout", "0"],
            env={
                **os.environ,
                "PATH": str(tmp_path),
                "GITHUB_EVENT_PATH": str(event),
                "GITHUB_EVENT_NAME": "pull_request",
                "GITHUB_REPOSITORY": "example/repo",
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    )
    assert_that(result.returncode).described_as(result.stderr).is_equal_to(
        0 if conclusion == "success" else 1
    )


def test_release_gate_rejects_missing_wrong_event_and_failed_rerun() -> None:
    """Latest current-head PR attempt wins over older successes and dispatches."""
    run = {
        "id": 1,
        "head_sha": HEAD,
        "event": "pull_request",
        "status": "completed",
        "conclusion": "success",
    }
    assert_that(latest_result([], HEAD, "pull_request")).is_equal_to("pending")
    pages = [{"workflow_runs": [{**run, "event": "workflow_dispatch"}]}]
    assert_that(latest_result(pages, HEAD, "pull_request")).is_equal_to("pending")
    pages[0]["workflow_runs"] = [
        run,
        {**run, "run_attempt": 2, "conclusion": "failure"},
    ]
    assert_that(latest_result(pages, HEAD, "pull_request")).is_equal_to("failure")
    pages[0]["workflow_runs"] = [
        {**run, "head_branch": "fix/ordinary", "conclusion": "success"}
    ]
    assert_that(latest_result(pages, HEAD, "pull_request", "release/v1")).is_equal_to(
        "pending"
    )


@pytest.mark.parametrize("mandatory", ["true", "false"])
@pytest.mark.parametrize("changes", ["success", "failure", "cancelled", "skipped"])
@pytest.mark.parametrize("native", ["success", "failure", "cancelled", "skipped"])
def test_harness_gate_fails_closed(
    monkeypatch: pytest.MonkeyPatch, mandatory: str, changes: str, native: str
) -> None:
    """Release/nightly/dispatch cannot pass on skipped or failed native work."""
    monkeypatch.setenv("SPIKE_MANDATORY", mandatory)
    needs = {
        "changes": {"result": changes, "outputs": {"changed": "false"}},
        "native": {"result": native},
        "offline-linux": {"result": native},
    }
    expected = changes == "success" and (
        native == "success" or (mandatory == "false" and native == "skipped")
    )
    assert_that(gate(needs)).is_equal_to(expected)


def test_workflow_wires_mandatory_jobs_and_release_gate() -> None:
    """The actual workflow must run after detector failure and bind the PR gate."""
    workflows = Path(__file__).resolve().parents[1] / ".github/workflows"
    spike = yaml.safe_load((workflows / "install-plane-spike.yml").read_text())
    native = spike["jobs"]["native"]
    assert_that(spike["on"]).contains_key(
        "merge_group", "schedule", "workflow_dispatch"
    )
    assert_that(native["if"]).contains(
        "!cancelled()",
        "needs.changes.result != 'success'",
        "github.event_name == 'schedule'",
        "github.event_name == 'workflow_dispatch'",
        "github.event_name == 'merge_group'",
        "startsWith(github.head_ref, 'release/')",
    )
    assert_that(spike["jobs"]["gate"]["if"]).is_equal_to("always()")
    assert_that(spike["jobs"]["gate"]["needs"]).contains_only(
        "changes",
        "native",
        "offline-linux",
    )
    setup = next(
        step
        for step in spike["jobs"]["changes"]["steps"]
        if step.get("uses", "").startswith("actions/setup-python@")
    )
    version = tuple(int(part) for part in setup["with"]["python-version"].split("."))
    assert_that(version >= (3, 12)).is_true()
    checks = yaml.safe_load((workflows / "all-checks-gate.yml").read_text())
    assert_that(checks["jobs"]["gate"]).does_not_contain_key("needs")
    release = yaml.safe_load((workflows / "install-plane-release-gate.yml").read_text())
    steps = release["jobs"]["release-spike"]["steps"]
    assert_that([step.get("run") for step in steps]).contains(
        "python3 scripts/ci/install_plane_release_gate.py"
    )
