"""Exercise mandatory release-head and fail-closed harness gates without network."""

import json
import os
import subprocess  # nosec B404 - local gate scripts and synthetic gh only
import sys
from pathlib import Path

import pytest
import yaml
from assertpy import assert_that
from ci.install_plane_gate import gate
from ci.install_plane_release_gate import latest_result, required_head

HEAD = "a" * 40


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
