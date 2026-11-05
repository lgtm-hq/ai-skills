"""Contract of the reusable ``ai-skills-validate`` workflow, its script and callers."""

import os
import re
import subprocess  # nosec B404 - runs this repository's own script with stubs
from pathlib import Path
from typing import Any

import pytest
import yaml
from assertpy import assert_that

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ai-skills-validate.yml"
SCRIPT = ROOT / "scripts/ci/ai_skills_validate.sh"
SHA = "0123456789abcdef0123456789abcdef01234567"
PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def _load(path: Path) -> dict[str, Any]:
    """Parse one workflow.

    Args:
        path: Workflow file.

    Returns:
        Parsed mapping.
    """
    document: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document


def test_reusable_workflow_inputs_permissions_and_pins() -> None:
    """``workflow_call`` inputs, read-only token, harden-runner and SHA pins."""
    workflow = _load(WORKFLOW)
    inputs = workflow["on"]["workflow_call"]["inputs"]
    assert_that(inputs).contains_only("engine-ref", "manifest-path", "strict")
    assert_that(inputs["engine-ref"]).contains_entry(
        {"required": True}, {"type": "string"}
    )
    assert_that(inputs["manifest-path"]).contains_entry(
        {"type": "string"}, {"default": "ai-skills.yaml"}
    )
    assert_that(inputs["strict"]).contains_entry({"type": "boolean"}, {"default": True})
    assert_that(workflow["permissions"]).is_equal_to({"contents": "read"})
    job = workflow["jobs"]["validate"]
    assert_that(job["permissions"]).is_equal_to({"contents": "read"})
    steps = job["steps"]
    assert_that(steps[0]["uses"]).starts_with("step-security/harden-runner@")
    assert_that(steps[0]["with"]["egress-policy"]).is_equal_to("block")
    for step in steps:
        if "uses" in step:
            assert_that(step["uses"]).matches(PINNED.pattern)
        if step.get("uses", "").startswith("actions/checkout@"):
            assert_that(step["with"]["persist-credentials"]).is_false()
    engine = next(step for step in steps if step.get("with", {}).get("repository"))
    assert_that(engine["with"]).contains_entry(
        {"repository": "lgtm-hq/ai-skills"}, {"ref": "${{ inputs.engine-ref }}"}
    )
    run = steps[-1]
    assert_that(run["run"]).is_equal_to(
        'bash "$ENGINE_DIR/scripts/ci/ai_skills_validate.sh"'
    )
    assert_that(run["env"]).contains_key(
        "ENGINE_REF", "MANIFEST_PATH", "STRICT", "ENGINE_DIR", "CALLER_DIR"
    )
    text = WORKFLOW.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "uses:" in line and "@" in line:
            assert_that(line).matches(r".*@[0-9a-f]{40} # v\d")


def test_ci_calls_reusable_workflow_for_catalog_and_fixture_vendor() -> None:
    """This catalog validates strictly, and a fixture vendor calls the workflow."""
    jobs = _load(ROOT / ".github/workflows/ci.yml")["jobs"]
    callers = {
        name: job
        for name, job in jobs.items()
        if job.get("uses") == "./.github/workflows/ai-skills-validate.yml"
    }
    assert_that(callers).contains_only("ai-skills-validate", "fixture-vendor-validate")
    assert_that(callers["ai-skills-validate"]["with"]).is_equal_to(
        {
            "engine-ref": "${{ github.sha }}",
            "manifest-path": "ai-skills.yaml",
            "strict": True,
        }
    )
    fixture = callers["fixture-vendor-validate"]["with"]
    assert_that(fixture["manifest-path"]).is_equal_to(
        "tests/fixtures/vendors/manifest/ai-skills.yaml"
    )
    assert_that((ROOT / fixture["manifest-path"]).is_file()).is_true()
    for job in callers.values():
        assert_that(job["permissions"]).is_equal_to({"contents": "read"})


@pytest.fixture
def stubs(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Put recording ``git`` and ``uv`` stubs first on PATH.

    Args:
        tmp_path: Test directory.

    Returns:
        Call log and the script environment.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    (bin_dir / "git").write_text(f'#!/bin/sh\nprintf "%s\\n" "${{STUB_HEAD:-{SHA}}}"\n')
    (bin_dir / "uv").write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\n')
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    engine, caller = tmp_path / "engine", tmp_path / "caller"
    (caller / "vendor").mkdir(parents=True)
    engine.mkdir()
    (caller / "vendor/ai-skills.yaml").write_text("apiVersion: ai-skills.dev/v1\n")
    environment = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "ENGINE_REF": SHA,
        "ENGINE_DIR": str(engine),
        "CALLER_DIR": str(caller),
        "MANIFEST_PATH": "vendor/ai-skills.yaml",
        "STRICT": "true",
    }
    return log, environment


def _script(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the CI script.

    Args:
        environment: Complete environment.

    Returns:
        Completed process.
    """
    return subprocess.run(  # nosec B603 B607 - fixed bash argv, repository script
        ["bash", str(SCRIPT)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_script_runs_pinned_engine_validate(stubs: tuple[Path, dict[str, str]]) -> None:
    """Validate runs offline; ``lock --fetch`` runs only for a committed lock."""
    log, environment = stubs
    engine = environment["ENGINE_DIR"]
    root = f"{environment['CALLER_DIR']}/vendor"
    result = _script(environment)
    assert_that(result.returncode).described_as(result.stderr).is_zero()
    prefix = f"run --project {engine} --locked --no-dev ai-skills-engine"
    assert_that(log.read_text().splitlines()).is_equal_to(
        [f"{prefix} validate --repo-root {root} --strict"]
    )
    log.unlink()
    (Path(root) / "ai-skills.lock").write_text("{}\n")
    result = _script(environment | {"STRICT": "false"})
    assert_that(result.returncode).described_as(result.stderr).is_zero()
    assert_that(log.read_text().splitlines()).is_equal_to(
        [
            f"{prefix} lock --fetch --repo-root {root}",
            f"{prefix} validate --repo-root {root}",
        ]
    )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"ENGINE_REF": "main"}, "engine-ref must be a full 40-hex commit SHA"),
        ({"ENGINE_REF": SHA.upper()}, "engine-ref must be a full 40-hex commit SHA"),
        ({"STRICT": "yes"}, "strict must be true or false"),
        ({"MANIFEST_PATH": "/etc/ai-skills.yaml"}, "manifest-path must be a relative"),
        ({"MANIFEST_PATH": "vendor/other.yaml"}, "manifest-path must be a relative"),
        ({"MANIFEST_PATH": "../vendor/ai-skills.yaml"}, "must not contain . or .."),
        ({"MANIFEST_PATH": "vendor/$(id)/ai-skills.yaml"}, "manifest-path must be"),
        ({"MANIFEST_PATH": "ai-skills.yaml"}, "is not a regular file"),
        ({"STUB_HEAD": "f" * 40}, "engine checkout is at"),
        ({"ENGINE_DIR": "/nonexistent"}, "must be checked-out directories"),
    ],
)
def test_script_fails_closed(
    stubs: tuple[Path, dict[str, str]], override: dict[str, str], message: str
) -> None:
    """Every malformed input or mismatched checkout stops before running uv."""
    log, environment = stubs
    result = _script(environment | override)
    assert_that(result.returncode).is_equal_to(1)
    assert_that(result.stderr).contains(message)
    assert_that(log.exists()).is_false()
