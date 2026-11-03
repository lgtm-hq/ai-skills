"""Keep the required parser differential in a prepared, fail-closed CI gate."""

import json
import os
import runpy
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
DISCOVERY = Path("scripts/ci/npm/manifest_renovate_tests.py")
QUALITY_TYPES = Path("scripts/ci/npm/manifest_fixture_type_tests.py")
FIXTURE_TYPES = [
    "bunx",
    ["--no-install", "tsc", "--noEmit", "-p", "tsconfig.fixtures.json"],
]


def test_real_renovate_entrypoint_is_in_strict_fixture_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The actual Python helper launches a maintained, typechecked TS fixture."""
    command = tmp_path / "bun"
    command.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "print(json.dumps({'entrypoint': sys.argv[1]}))\n"
    )
    command.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    run = runpy.run_path(str(ROOT / "scripts/ci/npm/renovate_helpers.py"))[
        "_run_renovate"
    ]
    monkeypatch.setitem(run.__wrapped__.__globals__, "_renovate_modules", dict)
    entrypoint = Path(run("vendors: []\n")["entrypoint"])
    assert_that(entrypoint.is_file()).is_true()
    assert_that(entrypoint.suffix).is_equal_to(".ts")
    project = ROOT / "npm/ai-skills/tsconfig.fixtures.json"
    config = json.loads(project.read_text())
    included = {
        path.resolve()
        for pattern in config["include"]
        for path in project.parent.glob(pattern)
    }
    assert_that(included).contains(entrypoint)
    base = json.loads((project.parent / config["extends"]).read_text())
    options = {**base["compilerOptions"], **config.get("compilerOptions", {})}
    for key in ("strict", "noUncheckedIndexedAccess"):
        assert_that(options[key]).is_true()


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
        assert_that(QUALITY_TYPES.is_relative_to(path)).is_false()
    assert_that(jobs["test"]["with"]["test-path"]).is_equal_to("tests")


@pytest.mark.parametrize(
    ("comparison_exit", "typecheck_exit"), [(0, 0), (23, 0), (0, 29)]
)
def test_actual_gateway_runner_requires_offline_comparison(
    tmp_path: Path, comparison_exit: int, typecheck_exit: int
) -> None:
    """Run the real shell gate; typecheck and parser failures stop later commands."""
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
        "if 'tsconfig.fixtures.json' in args:\n"
        "    sys.exit(int(os.environ['TYPECHECK_EXIT']))\n"
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
                "TYPECHECK_EXIT": str(typecheck_exit),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    )
    assert_that(result.returncode).described_as(result.stderr).is_equal_to(
        typecheck_exit or comparison_exit
    )
    calls = [json.loads(line) for line in trace.read_text().splitlines()]
    install = next(
        call for call in calls if call[:2] == ["bun", ["install", "--frozen-lockfile"]]
    )
    typecheck = next(call for call in calls if call[:2] == FIXTURE_TYPES)
    assert_that(calls.index(install)).is_less_than(calls.index(typecheck))
    assert_that(typecheck[3]).is_equal_to(str(tmp_path / "npm/ai-skills"))
    if typecheck_exit:
        assert_that(calls[calls.index(typecheck) + 1 :]).is_empty()
        return
    comparisons = [call for call in calls if "pytest" in call[1]]
    assert_that(comparisons).is_length(1)
    comparison = comparisons[0]
    assert_that(comparison).is_equal_to(
        [
            "uv",
            [
                "run",
                "--no-sync",
                "pytest",
                str(tmp_path / QUALITY_TYPES),
                str(tmp_path / COMPARISON),
                str(tmp_path / DISCOVERY),
            ],
            "1",
            str(tmp_path / "npm/ai-skills"),
        ]
    )
    assert_that(calls.index(typecheck)).is_less_than(calls.index(comparison))
    subsequent = calls[calls.index(comparison) + 1 :]
    if comparison_exit:
        assert_that(subsequent).is_empty()
    else:
        assert_that([call[:2] for call in subsequent]).is_equal_to(
            [
                ["bunx", ["--no-install", "tsc", "--noEmit"]],
                ["bun", ["test", "--coverage"]],
                ["bun", ["run", "build:launcher"]],
                ["bun", ["scripts/launcher-smoke.ts"]],
                ["bun", ["scripts/check-pack.ts"]],
            ]
        )
