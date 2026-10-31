"""Offline security coverage for shared installer pins and bootstrap consumers."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess  # nosec B404 - isolated shell fixtures, fixed argv, no network
from pathlib import Path
from typing import Any

import pytest
import yaml
from assertpy import assert_that

_ROOT = Path(__file__).resolve().parents[1]
_PINS = Path("scripts/tool-versions.sh")
_CHECK = "scripts/ci/check-tool-installers.sh"
_BOOTSTRAPS = ["scripts/install-validate-deps.sh", ".cursor/install.sh"]


def _write_executable(*, path: Path, text: str) -> None:
    """Write an executable shell fixture.

    Args:
        path: Destination in the temporary repository.
        text: Shell fixture body.
    """
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def installer_repo(tmp_path: Path) -> Path:
    """Copy real consumers and inject harmless installer payloads and hashes.

    Args:
        tmp_path: Isolated test directory.

    Returns:
        Fixture repository with no dependency downloads or host tool access.
    """
    for name in [
        str(_PINS),
        "scripts/lib/fetch-verified.sh",
        "scripts/install-ripgrep.sh",
        _CHECK,
        *_BOOTSTRAPS,
    ]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_ROOT / name, target)
    (tmp_path / "npm/ai-skills").mkdir(parents=True)
    for directory in ["bin", "payloads", "home", "temp"]:
        (tmp_path / directory).mkdir()
    pins = (tmp_path / _PINS).read_text(encoding="utf-8")
    for tool, location in [("uv", ".local/bin"), ("bun", ".bun/bin")]:
        payload = (
            "#!/bin/sh\n"
            f'echo "install {tool} $*" >> "$EVENT_LOG"\n'
            f'mkdir -p "$HOME/{location}"\n'
            f'cp "$PAYLOADS/{tool}" "$HOME/{location}/{tool}"\n'
        )
        (tmp_path / "payloads" / f"{tool}-install.sh").write_text(
            payload,
            encoding="utf-8",
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()
        pins = re.sub(
            rf'{tool.upper()}_INSTALLER_SHA256="[^"]+"',
            f'{tool.upper()}_INSTALLER_SHA256="{digest}"',
            pins,
        )
        version = re.search(rf'{tool.upper()}_VERSION="([^"]+)"', pins)
        if version is None:
            raise ValueError(f"Missing {tool} version in shared pins")
        _write_executable(
            path=tmp_path / "payloads" / tool,
            text=(
                "#!/bin/sh\n"
                f'echo "{tool} $*" >> "$EVENT_LOG"\n'
                'if [ "$1" = "--version" ]; then\n'
                f'  echo "{"uv " if tool == "uv" else ""}{version[1]}"\n'
                "fi\n"
            ),
        )
    (tmp_path / _PINS).write_text(pins, encoding="utf-8")
    for command in [
        "awk",
        "bash",
        "sh",
        "dirname",
        "mktemp",
        "rm",
        "cp",
        "mkdir",
        "sha256sum",
    ]:
        binary = shutil.which(command, path="/usr/bin:/bin")
        if binary is None:
            raise ValueError(f"Missing fixture utility: {command}")
        (tmp_path / "bin" / command).symlink_to(binary)
    _write_executable(path=tmp_path / "bin/rg", text="#!/bin/sh\nexit 0\n")
    _write_executable(
        path=tmp_path / "bin/curl",
        text=(
            "#!/bin/bash\nset -euo pipefail\n"
            "url= dest=\n"
            "while (( $# )); do\n"
            '  case "$1" in\n'
            '    -o) dest="$2"; shift 2 ;;\n'
            '    https://*) url="$1"; shift ;;\n'
            "    *) shift ;;\n"
            "  esac\n"
            "done\n"
            'printf "%s\\n" "$url" >> "$DOWNLOAD_LOG"\n'
            'case "$url" in\n'
            "  *astral.sh/uv/*) tool=uv ;;\n"
            "  *raw.githubusercontent.com/oven-sh/bun/*) tool=bun ;;\n"
            "  *) exit 90 ;;\n"
            "esac\n"
            'cp "$PAYLOADS/$tool-install.sh" "$dest"\n'
            'if [[ "${CURL_FAIL_TOOL:-$tool}" == "$tool" ]]; then\n'
            '  exit "${CURL_STATUS:-0}"\n'
            "fi\n"
        ),
    )
    return tmp_path


@pytest.fixture
def installer_env(installer_repo: Path) -> dict[str, str]:
    """Provide a minimal environment whose only network client is a local fake.

    Args:
        installer_repo: Isolated fixture repository.

    Returns:
        Environment with all tools, logs, and temporary files rooted in the fixture.
    """
    return {
        "PATH": str(installer_repo / "bin"),
        "HOME": str(installer_repo / "home"),
        "TMPDIR": str(installer_repo / "temp"),
        "PAYLOADS": str(installer_repo / "payloads"),
        "EVENT_LOG": str(installer_repo / "events"),
        "DOWNLOAD_LOG": str(installer_repo / "downloads"),
        "GITHUB_PATH": str(installer_repo / "github-path"),
    }


def _run(
    *,
    repo: Path,
    env: dict[str, str],
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    """Run a real shell consumer with injected local downloads.

    Args:
        repo: Fixture checkout root.
        env: Isolated fixture environment.
        args: Bash arguments without interpolation by a host shell.

    Returns:
        Captured process output and status.
    """
    return subprocess.run(  # nosec B603 - fixed bash, fixture argv, network stubbed
        ["/bin/bash", *args],
        env=env,
        cwd=repo / "home",
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize("script", _BOOTSTRAPS)
def test_bootstrap_installs_verified_payloads(
    installer_repo: Path,
    installer_env: dict[str, str],
    script: str,
) -> None:
    """Missing tools are installed from verified files before dependency commands."""
    result = _run(
        repo=installer_repo,
        env=installer_env,
        args=[str(installer_repo / script)],
    )
    assert_that(result.returncode).described_as(result.stderr).is_zero()
    events = (installer_repo / "events").read_text(encoding="utf-8")
    assert_that(events).contains("install uv", "uv sync --frozen")
    assert_that(events.index("install uv")).is_less_than(events.index("uv sync"))
    if script == ".cursor/install.sh":
        assert_that(events).contains(
            "install bun bun-v", "bun install --frozen-lockfile"
        )
        assert_that(events.index("install bun")).is_less_than(
            events.index("bun install")
        )
    else:
        assert_that((installer_repo / "github-path").read_text()).is_equal_to(
            f"{installer_repo}/home/.local/bin\n",
        )
    assert_that(list((installer_repo / "temp").iterdir())).is_empty()


@pytest.mark.parametrize("script", _BOOTSTRAPS)
def test_bootstrap_reuses_installed_tools(
    installer_repo: Path,
    installer_env: dict[str, str],
    script: str,
) -> None:
    """Existing pinned tools avoid installer downloads and still sync dependencies."""
    for tool in ["uv", "bun"]:
        shutil.copy(installer_repo / "payloads" / tool, installer_repo / "bin" / tool)
    result = _run(
        repo=installer_repo,
        env=installer_env,
        args=[str(installer_repo / script)],
    )
    assert_that(result.returncode).described_as(result.stderr).is_zero()
    assert_that((installer_repo / "downloads").exists()).is_false()
    assert_that((installer_repo / "events").read_text()).contains("uv sync --frozen")


def test_cursor_replaces_off_pin_tools(
    installer_repo: Path,
    installer_env: dict[str, str],
) -> None:
    """Cursor replaces off-pin executables before invoking dependency managers."""
    for tool in ["uv", "bun"]:
        _write_executable(
            path=installer_repo / "bin" / tool,
            text='#!/bin/sh\necho "0.0.0"\n',
        )
    result = _run(
        repo=installer_repo,
        env=installer_env,
        args=[str(installer_repo / ".cursor/install.sh")],
    )
    assert_that(result.returncode).described_as(result.stderr).is_zero()
    assert_that((installer_repo / "events").read_text()).contains(
        "install uv",
        "install bun",
        "uv sync --frozen",
        "bun install --frozen-lockfile",
    )
    assert_that((installer_repo / "downloads").read_text().splitlines()).is_length(2)


@pytest.mark.parametrize(
    ("script", "tool"),
    [
        (_BOOTSTRAPS[0], "uv"),
        (_BOOTSTRAPS[1], "uv"),
        (_BOOTSTRAPS[1], "bun"),
        (_CHECK, "uv"),
        (_CHECK, "bun"),
    ],
)
@pytest.mark.parametrize("failure", ["tampered", "download-error"])
def test_consumers_reject_unverified_installer(
    installer_repo: Path,
    installer_env: dict[str, str],
    script: str,
    tool: str,
    failure: str,
) -> None:
    """Corrupt bytes and failed downloads never reach execution or dependency sync."""
    if failure == "tampered":
        payload = installer_repo / "payloads" / f"{tool}-install.sh"
        payload.write_text(payload.read_text() + "# tampered bytes\n")
    else:
        installer_env["CURL_STATUS"] = "22"
        installer_env["CURL_FAIL_TOOL"] = tool
    result = _run(
        repo=installer_repo,
        env=installer_env,
        args=[str(installer_repo / script)],
    )
    assert_that(result.returncode).is_not_zero()
    if failure == "tampered":
        assert_that(result.stderr).contains("Checksum mismatch", "expected", "got")
    events = installer_repo / "events"
    log = events.read_text() if events.exists() else ""
    assert_that(log).does_not_contain(f"install {tool}", "sync", "bun install")
    assert_that(list((installer_repo / "temp").iterdir())).is_empty()


@pytest.mark.parametrize("tool", ["uv", "bun"])
def test_checksum_gate_rejects_version_only_update(
    installer_repo: Path,
    installer_env: dict[str, str],
    tool: str,
) -> None:
    """A changed installer at a new version fails even if both tools are on PATH."""
    for installed_tool in ["uv", "bun"]:
        shutil.copy(
            installer_repo / "payloads" / installed_tool,
            installer_repo / "bin" / installed_tool,
        )
    pin_file = installer_repo / _PINS
    pin_file.write_text(
        re.sub(
            rf'{tool.upper()}_VERSION="[^"]+"',
            f'{tool.upper()}_VERSION="999.0.0"',
            pin_file.read_text(),
        ),
    )
    payload = installer_repo / "payloads" / f"{tool}-install.sh"
    payload.write_text(payload.read_text() + "# new release bytes\n")
    result = _run(
        repo=installer_repo,
        env=installer_env,
        args=[str(installer_repo / _CHECK)],
    )
    assert_that(result.returncode).is_not_zero()
    assert_that(result.stderr).contains("Checksum mismatch", "999.0.0")
    assert_that((installer_repo / "events").exists()).is_false()
    assert_that(list((installer_repo / "temp").iterdir())).is_empty()


def test_checksum_gate_only_downloads_and_verifies(
    installer_repo: Path,
    installer_env: dict[str, str],
) -> None:
    """The unconditional gate checks both pins without executing either payload."""
    result = _run(
        repo=installer_repo,
        env=installer_env,
        args=[str(installer_repo / _CHECK)],
    )
    assert_that(result.returncode).described_as(result.stderr).is_zero()
    assert_that(result.stdout).contains("Verified uv", "Verified bun")
    assert_that((installer_repo / "downloads").read_text().splitlines()).is_length(2)
    assert_that((installer_repo / "events").exists()).is_false()
    assert_that(list((installer_repo / "temp").iterdir())).is_empty()


@pytest.mark.parametrize("mode", ["fallback", "hash-error", "download-error"])
def test_shared_fetch_handles_fallback_and_failures_in_conditionals(
    installer_repo: Path,
    installer_env: dict[str, str],
    mode: str,
) -> None:
    """Explicit failure returns hold even where Bash disables errexit for an if."""
    if mode == "fallback":
        (installer_repo / "bin/sha256sum").unlink()
        _write_executable(
            path=installer_repo / "bin/shasum",
            text='#!/bin/sh\n[ "$1" = -a ] && [ "$2" = 256 ] || exit 91\n'
            'shift 2\nexec /usr/bin/sha256sum "$@"\n',
        )
    elif mode == "hash-error":
        (installer_repo / "bin/sha256sum").unlink()
        _write_executable(
            path=installer_repo / "bin/sha256sum",
            text="#!/bin/sh\nexit 7\n",
        )
    else:
        installer_env["CURL_STATUS"] = "22"
    result = _run(
        repo=installer_repo,
        env=installer_env,
        args=[
            "-c",
            (
                'set -euo pipefail; source "$1/scripts/tool-versions.sh"; '
                'source "$1/scripts/lib/fetch-verified.sh"; '
                'if fetch_verified "$UV_INSTALLER_URL" "$UV_INSTALLER_SHA256" '
                '"$1/download"; then echo accepted; else exit $?; fi'
            ),
            "test-fetch",
            str(installer_repo),
        ],
    )
    assert_that(result.returncode).is_equal_to(
        {"fallback": 0, "hash-error": 7, "download-error": 22}[mode],
    )
    assert_that(result.stdout).is_equal_to("accepted\n" if mode == "fallback" else "")
    assert_that((installer_repo / "events").exists()).is_false()


def test_pin_file_has_no_load_time_side_effects(
    installer_repo: Path,
    installer_env: dict[str, str],
) -> None:
    """Sourcing pins only assigns values, with no processes or output."""
    text = (_ROOT / _PINS).read_text(encoding="utf-8")
    statements = [
        line for line in text.splitlines() if line and not line.startswith("#")
    ]
    assert_that(statements).is_length(6)
    for statement in statements:
        assert_that(statement).matches(r'^(UV|BUN)_[A-Z0-9_]+="[^"`]*"$')
        assert_that(statement).does_not_contain("$(")
    result = _run(
        repo=installer_repo,
        env=installer_env,
        args=["-c", 'source "$1"', "test-pins", str(installer_repo / _PINS)],
    )
    assert_that(result.returncode).is_zero()
    assert_that(result.stdout + result.stderr).is_empty()
    assert_that((installer_repo / "events").exists()).is_false()
    assert_that((installer_repo / "downloads").exists()).is_false()


def test_scripts_do_not_pipe_downloads_to_shells() -> None:
    """Reject the original curl/wget-to-shell pattern across bootstrap sources."""
    unsafe = re.compile(
        r"\b(?:curl|wget)\b[^|;]*\|\s*(?:(?:ba|da|z|k)?sh)\b",
        re.MULTILINE,
    )
    violations = []
    for directory in ["scripts", ".cursor"]:
        for path in (_ROOT / directory).rglob("*"):
            if (
                path.is_file()
                and path.suffix in {".sh", ".py"}
                and unsafe.search(path.read_text(encoding="utf-8"))
            ):
                violations.append(str(path.relative_to(_ROOT)))
    assert_that(violations).is_empty()


def test_shared_pin_file_is_only_version_definition() -> None:
    """Bootstrap consumers cannot introduce independent tool version pins."""
    definitions = []
    for directory in ["scripts", ".cursor"]:
        for path in (_ROOT / directory).rglob("*.sh"):
            if re.search(
                r"^\s*(?:export\s+)?(?:UV|BUN)_VERSION=", path.read_text(), re.MULTILINE
            ):
                definitions.append(path.relative_to(_ROOT))
    assert_that(definitions).is_equal_to([_PINS])


def test_renovate_extracts_both_pins_and_bun_release_prefix() -> None:
    """The committed regex discovers both shared pins and extracts Bun tag versions."""
    config = json.loads((_ROOT / "renovate.json").read_text())
    manager = next(
        manager
        for manager in config["customManagers"]
        if "/^scripts/tool-versions\\.sh$/" in manager["managerFilePatterns"]
    )
    pattern = manager["matchStrings"][0].replace("(?<", "(?P<")
    pins = (_ROOT / _PINS).read_text()
    matches = [match.groupdict() for match in re.finditer(pattern, pins)]
    assert_that(matches).is_length(2)
    assert_that([item["depName"] for item in matches]).is_equal_to(
        ["astral-sh/uv", "oven-sh/bun"],
    )
    for tool, match in zip(["UV", "BUN"], matches, strict=True):
        assert_that(match["datasource"]).is_equal_to("github-releases")
        assert_that(pins).contains(f'{tool}_VERSION="{match["currentValue"]}"')
    extract = matches[1]["extractVersion"].replace("(?<", "(?P<")
    release = re.fullmatch(extract, "bun-v9.8.7")
    assert_that(release).is_not_none()
    if release is not None:
        assert_that(release["version"]).is_equal_to("9.8.7")


def test_ci_checks_pins_with_restricted_egress_and_pinned_actions() -> None:
    """CI always runs the network check behind block-mode runner hardening."""
    workflow: dict[str, Any] = yaml.safe_load(
        (_ROOT / ".github/workflows/ci.yml").read_text()
    )
    job = workflow["jobs"]["verify-installers"]
    assert_that(job).does_not_contain_key("if")
    assert_that(job["permissions"]).is_equal_to({"contents": "read"})
    steps = job["steps"]
    for step in steps:
        if "uses" in step:
            assert_that(step["uses"]).matches(r"@[0-9a-f]{40}$")
    hardening = steps[0]["with"]
    assert_that(hardening["egress-policy"]).is_equal_to("block")
    assert_that(hardening["allowed-endpoints"]).contains(
        "astral.sh:443",
        "releases.astral.sh:443",
        "raw.githubusercontent.com:443",
    )
    assert_that(steps[-1]["run"]).is_equal_to(f"bash {_CHECK}")
