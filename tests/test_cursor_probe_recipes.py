"""Execute the personal-Mac handoff with fake Cursor and disposable storage."""

import json
import re
import shutil
import subprocess  # nosec B404 - offline Bash recipes with a local fake executable
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest
from assertpy import assert_that


@pytest.fixture
def launch_recipe(
    tmp_path: Path,
) -> Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]]:
    """Extract actual Markdown commands; never launch a desktop or read real HOME."""
    root = Path(__file__).resolve().parents[1]
    document = (root / "docs/parity/cursor-probe-checklist.md").read_text(
        encoding="utf-8",
    )
    blocks = {
        block.splitlines()[0]: block
        for match in re.findall(
            r"^ {0,3}```bash\n(.*?)^ {0,3}```",
            document,
            flags=re.MULTILINE | re.DOTALL,
        )
        if (block := textwrap.dedent(match))
    }
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Documented recipes require Bash")
    fake_bin = tmp_path / "fake bin"
    fake_bin.mkdir()
    hook = shutil.copy2(
        src=root / "tests/fixtures/host-probe/probe-sentinel/hooks/sentinel.py",
        dst=tmp_path / "hook.py",
    )
    cursor = fake_bin / "cursor"
    cursor.write_text(
        f"#!{sys.executable}\n"
        "import json, os, runpy, sys\n"
        f"runpy.run_path({str(hook)!r})\n"
        "print(json.dumps({'argv': sys.argv[1:], 'env': dict(os.environ)}))\n",
        encoding="utf-8",
    )
    cursor.chmod(0o700)
    home = tmp_path / "original home"
    home.mkdir()
    ambient = tmp_path / "ambient tmp"
    ambient.mkdir()
    (ambient / "probe-hook.log").write_text("unrelated runtime log\n")
    project = tmp_path / "case/project"
    project.mkdir(parents=True)
    environment = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": str(ambient),
        "probe_case": str(project.parent),
        "GITHUB_TOKEN": str(tmp_path / "synthetic-credential"),
        "SSH_AUTH_SOCK": "synthetic-agent-must-not-reach-cursor",
        "XDG_CONFIG_HOME": str(home / "ambient-config"),
        "DISPLAY": ":synthetic-not-for-macos",
    }

    def run(
        recipe: str,
        overrides: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        """Run selected source blocks using synthetic environment values only."""
        script = blocks["# Isolated IDE common setup"] + blocks["# macOS launch"]
        if recipe != "macOS launch":
            script += blocks[f"# {recipe}"]
        return subprocess.run(  # nosec B603 - fixed Bash, local docs and fake PATH
            [bash, "--noprofile", "--norc", "-eu", "-c", script],
            cwd=tmp_path,
            env={**environment, **overrides},
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    return run


def test_macos_recipe_isolates_storage_with_empty_session_array(
    launch_recipe: Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """Nounset and an empty session array still launch with only scratch storage."""
    result = launch_recipe("macOS launch", {})
    assert_that(result.returncode).is_zero()
    assert_that(result.stderr).is_empty()
    captured = json.loads(result.stdout)
    environment = captured["env"]
    storage = {
        "HOME": "home",
        "TMPDIR": "tmp",
        "XDG_CONFIG_HOME": "config",
        "XDG_CACHE_HOME": "cache",
        "XDG_DATA_HOME": "data",
        "XDG_STATE_HOME": "state",
    }
    for name, directory in storage.items():
        assert_that(environment[name]).is_equal_to(str(tmp_path / "case" / directory))
    # CPython may insert LC_CTYPE during locale coercion in the fake executable.
    assert_that(set(environment)).is_subset_of({*storage, "PATH", "LC_CTYPE"})
    assert_that(captured["argv"]).is_equal_to(
        [
            "--new-window",
            "--user-data-dir",
            str(tmp_path / "case/user-data"),
            "--extensions-dir",
            str(tmp_path / "case/extensions"),
            str(tmp_path / "case/project"),
        ],
    )
    document = (
        Path(__file__).resolve().parents[1] / "docs/parity/cursor-probe-checklist.md"
    ).read_text()
    # Bash >=4.4 relaxed nounset arrays; require the guard for the 3.2 contract.
    assert_that(document).contains('${probe_session[@]+"${probe_session[@]}"}')


@pytest.mark.parametrize("ambient_tmp", ["ambient", "empty"])
def test_hook_inspection_reads_child_case_log(
    launch_recipe: Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]],
    tmp_path: Path,
    ambient_tmp: str,
) -> None:
    """The actual kit hook and documented inspection agree despite parent TMPDIR."""
    overrides = {"TMPDIR": ""} if ambient_tmp == "empty" else {}
    result = launch_recipe("Isolated hook inspection", overrides)
    assert_that(result.returncode).is_zero()
    assert_that(result.stdout.splitlines()[-1]).is_equal_to("PROBE-7f3a-lifecycle")
    assert_that((tmp_path / "ambient tmp/probe-hook.log").read_text()).is_equal_to(
        "unrelated runtime log\n",
    )


def test_cleanup_removes_isolated_log_and_preserves_ambient_log(
    launch_recipe: Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """Documented cleanup removes the owned case without touching ambient runtime."""
    result = launch_recipe("Isolated case cleanup", {})
    assert_that(result.returncode).is_zero()
    assert_that((tmp_path / "case").exists()).is_false()
    assert_that((tmp_path / "ambient tmp/probe-hook.log").read_text()).is_equal_to(
        "unrelated runtime log\n",
    )
