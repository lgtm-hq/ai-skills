"""Execute documented launch recipes with a fake Cursor and synthetic session."""

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
    """Extract actual Markdown commands and supply no real desktop environment."""
    document = (
        Path(__file__).resolve().parents[1] / "docs/parity/cursor-probe-checklist.md"
    ).read_text(encoding="utf-8")
    blocks = {
        block.splitlines()[0]: block
        for match in re.findall(
            r"^   ```bash\n(.*?)^   ```",
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
    cursor = fake_bin / "cursor"
    cursor.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "print(json.dumps({'argv': sys.argv[1:], 'env': dict(os.environ)}))\n",
        encoding="utf-8",
    )
    cursor.chmod(0o700)
    home = tmp_path / "original home"
    home.mkdir()
    (home / ".Xauthority").write_bytes(b"Synthetic authority; never a real cookie")
    (tmp_path / "runtime").mkdir()
    project = tmp_path / "case/project"
    project.mkdir(parents=True)
    environment = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "HOME": str(home),
        "probe_case": str(project.parent),
        "DISPLAY": ":offline",
        "WAYLAND_DISPLAY": "wayland-offline",
        "XDG_RUNTIME_DIR": str(tmp_path / "runtime"),
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=offline-session-bus",
        "GITHUB_TOKEN": str(tmp_path / "synthetic-credential"),
        "SSH_AUTH_SOCK": "synthetic-agent-must-not-reach-cursor",
        "XDG_CONFIG_HOME": str(home / "ambient-config"),
        "XDG_CACHE_HOME": str(home / "ambient-cache"),
    }

    def run(
        recipe: str,
        overrides: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        """Execute a selected documented block using synthetic values only."""
        script = blocks["# Isolated IDE common setup"] + blocks[f"# {recipe}"]
        return (
            subprocess.run(  # nosec B603 - fixed Bash, extracted local docs, fake PATH
                [bash, "--noprofile", "--norc", "-eu", "-c", script],
                cwd=tmp_path,
                env={**environment, **overrides},
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        )

    return run


@pytest.mark.parametrize(
    ("recipe", "session", "platform_flag"),
    [
        (
            "Linux X11 launch",
            {"DISPLAY", "XAUTHORITY", "XDG_SESSION_TYPE"},
            "--ozone-platform=x11",
        ),
        (
            "Linux Wayland launch",
            {
                "WAYLAND_DISPLAY",
                "XDG_RUNTIME_DIR",
                "DBUS_SESSION_BUS_ADDRESS",
                "XDG_SESSION_TYPE",
            },
            "--ozone-platform=wayland",
        ),
        ("macOS launch", set(), None),
    ],
)
def test_platform_recipe_isolates_storage_and_allowlists_session(
    launch_recipe: Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]],
    tmp_path: Path,
    recipe: str,
    session: set[str],
    platform_flag: str | None,
) -> None:
    """Fake launches preserve only explicit session access and scratch storage."""
    result = launch_recipe(recipe, {})
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
    assert_that(set(environment)).is_subset_of(
        {*storage, *session, "PATH", "LC_CTYPE"},
    )
    assert_that(environment).does_not_contain_key("GITHUB_TOKEN", "SSH_AUTH_SOCK")
    argv = [
        "--new-window",
        "--user-data-dir",
        str(tmp_path / "case/user-data"),
        "--extensions-dir",
        str(tmp_path / "case/extensions"),
    ]
    if platform_flag is not None:
        argv.append(platform_flag)
    argv.append(str(tmp_path / "case/project"))
    assert_that(captured["argv"]).is_equal_to(argv)
    if recipe == "Linux X11 launch":
        assert_that(environment["DISPLAY"]).is_equal_to(":offline")
        assert_that(environment["XAUTHORITY"]).is_equal_to(
            str(tmp_path / "original home/.Xauthority"),
        )
    elif recipe == "Linux Wayland launch":
        assert_that(environment["WAYLAND_DISPLAY"]).is_equal_to("wayland-offline")
        assert_that(environment["XDG_RUNTIME_DIR"]).is_equal_to(
            str(tmp_path / "runtime")
        )
        assert_that(environment["DBUS_SESSION_BUS_ADDRESS"]).is_equal_to(
            "unix:path=offline-session-bus",
        )


@pytest.mark.parametrize("authority", ["explicit", "relative", "empty"])
def test_x11_resolves_authority_before_changing_home(
    launch_recipe: Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]],
    tmp_path: Path,
    authority: str,
) -> None:
    """Explicit and relative authority paths work; empty uses the original HOME."""
    expected = tmp_path / "original home/.Xauthority"
    if authority != "empty":
        expected = tmp_path / "session authority"
        expected.write_bytes(b"Synthetic session authority")
    value = {
        "explicit": str(expected),
        "relative": expected.name,
        "empty": "",
    }[authority]
    result = launch_recipe("Linux X11 launch", {"XAUTHORITY": value})
    assert_that(result.returncode).is_zero()
    assert_that(json.loads(result.stdout)["env"]["XAUTHORITY"]).is_equal_to(
        str(expected)
    )
    assert_that((tmp_path / "case/home/.Xauthority").exists()).is_false()
    assert_that(result.stdout).does_not_contain("Synthetic session authority")


@pytest.mark.parametrize(
    ("recipe", "overrides"),
    [
        ("Linux X11 launch", {"DISPLAY": ""}),
        ("Linux X11 launch", {"XAUTHORITY": "missing-authority"}),
        ("Linux Wayland launch", {"WAYLAND_DISPLAY": ""}),
        ("Linux Wayland launch", {"XDG_RUNTIME_DIR": ""}),
        ("Linux Wayland launch", {"XDG_RUNTIME_DIR": "relative-runtime"}),
        ("Linux Wayland launch", {"XDG_RUNTIME_DIR": "/nonexistent-offline-runtime"}),
        ("Linux Wayland launch", {"DBUS_SESSION_BUS_ADDRESS": ""}),
    ],
)
def test_missing_session_requirements_prevent_launch(
    launch_recipe: Callable[[str, dict[str, str]], subprocess.CompletedProcess[str]],
    recipe: str,
    overrides: dict[str, str],
) -> None:
    """Absent prerequisites cannot reach even the fake Cursor executable."""
    result = launch_recipe(recipe, overrides)
    assert_that(result.returncode).is_not_zero()
    assert_that(result.stdout).is_empty()
