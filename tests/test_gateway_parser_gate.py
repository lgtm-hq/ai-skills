"""Keep the required parser differential in a prepared, fail-closed CI gate."""

import json
import os
import shutil
import subprocess  # nosec B404 - local trusted runner and offline command stubs
import sys
import tomllib
from pathlib import Path

import pytest
import yaml
from assertpy import assert_that

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path("scripts/ci/npm/check_ai_skills_package.sh")
COMPARISON = Path("scripts/ci/npm/manifest_yaml_boundary_tests.py")


@pytest.mark.parametrize("prepared_gate", [False, True])
def test_no_runtime_python_and_gateway_boundaries(
    tmp_path: Path, prepared_gate: bool
) -> None:
    """No Bun or node modules: Python passes, the mandatory runtime gate errors."""
    for directory in ("src", "skills"):
        shutil.copytree(src=ROOT / directory, dst=tmp_path / directory)
    for relative in (
        Path("ai-skills.yaml"),
        Path("pyproject.toml"),
        Path("npm/ai-skills/package.json"),
        Path("tests/manifest_helpers.py"),
        Path("tests/test_manifest_yaml_boundary.py"),
        COMPARISON,
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src=ROOT / relative, dst=destination)
    empty_path = tmp_path / "empty-bin"
    empty_path.mkdir()
    assert_that(shutil.which("bun", path=str(empty_path))).is_none()
    modules = tmp_path / "npm/ai-skills/node_modules"
    assert_that(modules.exists()).is_false()
    target = (
        COMPARISON if prepared_gate else Path("tests/test_manifest_yaml_boundary.py")
    )
    result = (
        subprocess.run(  # nosec B603 - real Python-only pytest, no command acquisition
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                str(target),
            ],
            cwd=tmp_path,
            env={
                **os.environ,
                "PATH": str(empty_path),
                "PYTHONPATH": os.pathsep.join(
                    [str(tmp_path / "src"), str(Path(pytest.__file__).parents[1])]
                ),
                "RENOVATE_TEST_NODE_MODULES": str(modules),
                "UV_OFFLINE": "1",
                "PYTEST_ADDOPTS": "",
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    )
    assert_that(result.returncode).described_as(
        result.stdout + result.stderr
    ).is_equal_to(1 if prepared_gate else 0)
    assert_that(result.stdout).does_not_contain("skipped")
    assert_that(result.stdout).contains("6 errors" if prepared_gate else "6 passed")
    if prepared_gate:
        assert_that(result.stdout).contains("FileNotFoundError", "yaml/package.json")
    assert_that(modules.exists()).is_false()


def test_workflow_prepares_gateway_parser_gate() -> None:
    """The full CI gateway prepares both runtimes before invoking the real runner."""
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    steps = jobs["gateway"]["steps"]
    gate = next(
        index for index, step in enumerate(steps) if step.get("run") == f"bash {RUNNER}"
    )
    preceding = steps[:gate]
    for action in ("actions/checkout@", "oven-sh/setup-bun@", "astral-sh/setup-uv@"):
        assert_that(
            any(step.get("uses", "").startswith(action) for step in preceding)
        ).is_true()
    assert_that([step.get("run") for step in preceding]).contains("uv sync --frozen")
    assert_that(steps[gate].get("continue-on-error", False)).is_false()
    assert_that(jobs["gateway"].get("if")).is_none()
    python_paths = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"][
        "pytest"
    ]["ini_options"]["testpaths"]
    assert_that(python_paths).contains("tests")
    for path in python_paths:
        assert_that(COMPARISON.is_relative_to(path)).is_false()
    assert_that(jobs["test"]["with"]["test-path"]).is_equal_to("tests")


@pytest.mark.parametrize("comparison_exit", [0, 23])
def test_actual_gateway_runner_requires_offline_comparison(
    tmp_path: Path, comparison_exit: int
) -> None:
    """Execute the changed shell helper; parser failures must stop the full gate."""
    runner = tmp_path / RUNNER
    runner.parent.mkdir(parents=True)
    shutil.copy2(src=ROOT / RUNNER, dst=runner)
    (tmp_path / "npm/ai-skills").mkdir(parents=True)
    (tmp_path / "plugins-baked").mkdir()
    (tmp_path / "plugins-baked/BAKE.json").write_text("{}\n")
    commands = tmp_path / "commands"
    commands.mkdir()
    trace = tmp_path / "trace.jsonl"
    stub = (
        f"#!{sys.executable}\n"
        "import json, os, sys\nfrom pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "with Path(os.environ['TRACE']).open('a') as stream:\n"
        "    stream.write(json.dumps([Path(sys.argv[0]).name, args, "
        "os.environ.get('UV_OFFLINE'), str(Path.cwd())]) + '\\n')\n"
        "if '-e' in args:\n    print('0.0.0-dev')\n"
        "if 'pytest' in args:\n    sys.exit(int(os.environ['COMPARISON_EXIT']))\n"
    )
    for name in ("uv", "bun", "bunx"):
        command = commands / name
        command.write_text(stub)
        command.chmod(0o755)
    result = (
        subprocess.run(  # nosec B603 B607 - fixed shell runner, all acquisition stubbed
            ["bash", str(runner)],
            cwd=tmp_path,
            env={
                **os.environ,
                "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
                "TRACE": str(trace),
                "COMPARISON_EXIT": str(comparison_exit),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    )
    assert_that(result.returncode).described_as(result.stderr).is_equal_to(
        comparison_exit
    )
    calls = [json.loads(line) for line in trace.read_text().splitlines()]
    comparisons = [call for call in calls if "pytest" in call[1]]
    assert_that(comparisons).is_length(1)
    comparison = comparisons[0]
    assert_that(comparison).is_equal_to(
        [
            "uv",
            ["run", "--no-sync", "pytest", str(tmp_path / COMPARISON)],
            "1",
            str(tmp_path / "npm/ai-skills"),
        ]
    )
    install = next(
        call for call in calls if call[:2] == ["bun", ["install", "--frozen-lockfile"]]
    )
    assert_that(calls.index(install)).is_less_than(calls.index(comparison))
    subsequent = calls[calls.index(comparison) + 1 :]
    if comparison_exit:
        assert_that(subsequent).is_empty()
    else:
        assert_that([call[:2] for call in subsequent]).contains(
            ["bunx", ["tsc", "--noEmit"]], ["bun", ["test", "--coverage"]]
        )
