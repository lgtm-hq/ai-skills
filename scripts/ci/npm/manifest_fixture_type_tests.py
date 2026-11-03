"""Exercise root Lintro's real compiler boundary in the prepared gateway job.

The Python-only job has no TypeScript dependencies. These tests require the
already installed compiler and runtime declarations; they never acquire tools.
"""

import json
import os
import shutil
import subprocess  # nosec B404 - prepared local compiler, no shell or acquisition
from collections.abc import Iterator
from pathlib import Path

import pytest
from assertpy import assert_that
from lintro.config.config_loader import clear_config_cache, get_config
from lintro.enums.action import Action
from lintro.tools.tsc.definition import TscPlugin
from lintro.utils.execution.tool_configuration import (
    configure_tool_for_execution,
    get_tools_to_run,
)
from lintro.utils.unified_config import UnifiedConfigManager

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path("tests/fixtures/manifest")


@pytest.fixture
def quality_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    """Copy the real project topology and share prepared dependencies read-only.

    Args:
        tmp_path: Isolated checkout destination.
        monkeypatch: Scoped environment and working directory changes.

    Yields:
        Root with the real quality and TypeScript configurations and fixtures.
    """
    gateway = Path("npm/ai-skills")
    modules = ROOT / gateway / "node_modules"
    assert_that((modules / ".bin/tsc").is_file()).is_true()
    paths = [
        Path(".lintro-config.yaml"),
        Path(".lintro-ignore"),
        Path("pyproject.toml"),
        gateway / "tsconfig.json",
        gateway / "tsconfig.fixtures.json",
        Path("research/install-plane-spike/ts/tsconfig.json"),
        *[path.relative_to(ROOT) for path in (ROOT / FIXTURES).glob("*.ts")],
        FIXTURES / "tsconfig.json",
    ]
    for path in paths:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src=ROOT / path, dst=destination)
    (tmp_path / gateway / "node_modules").symlink_to(
        modules,
        target_is_directory=True,
    )
    monkeypatch.setenv("PATH", f"{modules / '.bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("LINTRO_GLOBAL_CONFIG", "off")
    monkeypatch.chdir(tmp_path)
    clear_config_cache()
    try:
        yield tmp_path
    finally:
        clear_config_cache()


@pytest.mark.parametrize(
    "control",
    ["valid", "undiscovered-project", "missing-types", "unchecked-index"],
)
def test_root_lintro_checks_fixture_runtime_types(
    quality_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    control: str,
) -> None:
    """Run configured discovery and its real argv, including failing controls."""
    project = quality_repo / FIXTURES / "tsconfig.json"
    if control == "undiscovered-project":
        project.unlink()
    elif control == "missing-types":
        config = json.loads(project.read_text())
        config["compilerOptions"]["typeRoots"] = ["./missing-runtime-types"]
        project.write_text(json.dumps(config))
    elif control == "unchecked-index":
        (project.parent / "unchecked-index.ts").write_text(
            "export {}; const values: string[] = []; values[0].toUpperCase();\n"
        )

    config = get_config(reload=True)
    selected = get_tools_to_run(tools=None, action=Action.CHECK, lintro_config=config)
    assert_that(selected.to_run).contains("tsc")
    tool = configure_tool_for_execution(
        tool=TscPlugin(),
        tool_name="tsc",
        config_manager=UnifiedConfigManager(),
        tool_option_dict={},
        exclude=None,
        include_venv=False,
        incremental=False,
        action=Action.CHECK,
        selected_tools=set(selected.to_run),
        lintro_config=config,
    )
    assert_that(tool.options.get("auto_install", False)).is_false()
    calls: list[tuple[list[str], str | None, str]] = []
    execute = tool._run_subprocess

    def record(
        cmd: list[str],
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> tuple[bool, str]:
        """Record the actual command and output while executing it unchanged.

        Args:
            cmd: Lintro-selected compiler argv.
            timeout: Lintro timeout in seconds.
            cwd: Lintro-selected project directory.

        Returns:
            The real compiler's success flag and output.
        """
        success, output = execute(cmd=cmd, timeout=timeout, cwd=cwd)
        calls.append((cmd, cwd, output))
        print(
            json.dumps({"argv": cmd, "cwd": cwd, "success": success, "output": output})
        )
        return success, output

    monkeypatch.setattr(tool, "_run_subprocess", record)
    result = tool.check(paths=["."], options={})
    assert_that(result.skipped).is_false()
    assert_that(calls).is_length(1)
    command, cwd, output = calls[0]
    assert_that(command).contains("--noEmit", "--pretty", "false")
    assert_that(result.success).described_as(output).is_equal_to(control == "valid")
    if control == "undiscovered-project":
        assert_that(command).does_not_contain("--project")
        assert_that(command).contains(
            str(FIXTURES / "renovate-parse.ts"),
            str(FIXTURES / "renovate-runner.ts"),
        )
        assert_that(result.issues_count).is_equal_to(13)
        return
    assert_that(command[command.index("--project") + 1]).is_equal_to(str(project))
    assert_that(cwd).is_equal_to(str(project.parent))
    if control == "missing-types":
        assert_that(output).contains("TS2688", "bun-types")
    elif control == "unchecked-index":
        assert_that(output).contains("unchecked-index.ts", "possibly 'undefined'")
    else:
        listed = subprocess.run(  # nosec B603 - real recorded compiler argv, no shell
            [*command, "--listFilesOnly"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert_that(listed.returncode).described_as(listed.stderr).is_zero()
        assert_that(listed.stdout).contains(
            str(project.parent / "renovate-parse.ts"),
            str(project.parent / "renovate-runner.ts"),
            "/bun-types/index.d.ts",
            "/@types/node/index.d.ts",
        )
