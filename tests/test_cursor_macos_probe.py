"""Validate embedded Cursor kit programs offline, without an IDE or HOME probe."""

import json
import re
import shutil
import subprocess  # nosec B404 - extracted local sentinels and Bash syntax only
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from assertpy import assert_that

type EmbeddedRunner = Callable[
    [str, list[str], str, dict[str, str]], subprocess.CompletedProcess[str]
]


SCRIPT = Path(__file__).parent / "fixtures/host-probe/cursor-macos-probe-driver.sh"


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        (None, "global"),
        ("isolated", "isolated"),
        ("global", "global"),
        ("", None),
        ("relative", None),
        ("missing", None),
        ("no-launcher", None),
        ("not-executable", None),
        ("directory-launcher", None),
    ],
)
def test_app_selection_never_falls_back_from_explicit_override(
    tmp_path: Path,
    override: str | None,
    expected: str | None,
) -> None:
    """Use two fake installed apps; invalid overrides must never launch either."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required for disposable app selection tests")
    match = re.search(
        r"^select_cursor_app\(\) \{.*?^\}",
        SCRIPT.read_text(),
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        pytest.fail("Expected app selection function is missing")
    apps = {
        "global": tmp_path / "Applications/Cursor.app",
        "isolated": tmp_path / "isolated home/Applications/Cursor.app",
    }
    for name, app in apps.items():
        cli = app / "Contents/Resources/app/bin/cursor"
        cli.parent.mkdir(parents=True)
        cli.write_text(f"#!/bin/sh\nprintf '%s\\n' {name} >> launches\n")
        cli.chmod(0o700)
    environment = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    if override is not None:
        selected = apps.get(override, tmp_path / override)
        if override in {"no-launcher", "not-executable", "directory-launcher"}:
            selected.mkdir()
            cli = selected / "Contents/Resources/app/bin/cursor"
            if override == "directory-launcher":
                cli.mkdir(parents=True)
            elif override == "not-executable":
                cli.parent.mkdir(parents=True)
                cli.write_text("#!/bin/sh\nexit 99\n")
                cli.chmod(0o600)
        environment["CURSOR_PROBE_APP"] = (
            override if override in {"", "relative"} else str(selected)
        )
    # Supply synthetic default candidates to the exact selection boundary. Never
    # inspect /Applications, and never execute a default or real host launcher.
    result = subprocess.run(  # nosec B603 - extracted selector, disposable fake apps
        [
            bash,
            "--noprofile",
            "--norc",
            "-euc",
            match.group(0) + '\nselect_cursor_app "$@"\n"$CLI"',
            "app-selection-test",
            str(apps["global"]),
            str(apps["isolated"]),
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    launches = tmp_path / "launches"
    if expected is None:
        assert_that(result.returncode).is_not_zero()
        assert_that(result.stderr).contains("Cursor")
        assert_that(launches.exists()).is_false()
    else:
        assert_that(result.returncode).described_as(result.stderr).is_zero()
        assert_that(launches.read_text().splitlines()).is_equal_to([expected])


@pytest.fixture
def embedded_program(
    tmp_path: Path,
) -> EmbeddedRunner:
    """Extract embedded Python and execute it only against disposable inputs."""
    source = SCRIPT.read_text(encoding="utf-8")

    def run(
        program: str,
        args: list[str],
        stdin: str,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        """Run the exact here-document body, never the interactive driver."""
        if program == "report":
            match = re.search(
                r"write_report\(\).*?<<'PY'\n(.*?)\nPY", source, re.DOTALL
            )
            if match is None:
                pytest.fail("Embedded reporter is missing")
            body = match.group(1)
        else:
            match = re.search(
                rf'cat >"\$SENT/{program}\.py" <<\'PY\'\n(.*?)\nPY',
                source,
                re.DOTALL,
            )
            if match is None:
                pytest.fail("Embedded sentinel is missing")
            body = match.group(1)
        executable = tmp_path / f"{program}.py"
        executable.write_text(body, encoding="utf-8")
        return (
            subprocess.run(  # nosec B603 - current Python and extracted local program
                [sys.executable, "-I", str(executable), *args],
                input=stdin,
                text=True,
                capture_output=True,
                cwd=tmp_path,
                env={"HOME": str(tmp_path / "home"), **environment},
                timeout=5,
                check=False,
            )
        )

    return run


@pytest.mark.parametrize("event", ['{"hook_event_name":"sessionStart"}', "[]", "bad"])
def test_embedded_hook_uses_only_isolated_tmpdir(
    embedded_program: EmbeddedRunner,
    tmp_path: Path,
    event: str,
) -> None:
    """Tagged lifecycle writes are inspected at the child TMPDIR, never ambient logs."""
    isolated = tmp_path / "case/tmp"
    isolated.mkdir(parents=True)
    ambient = tmp_path / "probe-hook.log"
    ambient.write_text("ambient runtime\n")
    result = embedded_program("hook", ["ue"], event, {"TMPDIR": str(isolated)})
    assert_that(result.returncode).is_zero()
    assert_that(result.stdout.strip()).is_equal_to("{}")
    assert_that((isolated / "probe-hook.log").read_text()).starts_with(
        "PROBE-7f3a-lifecycle-ue ",
    )
    assert_that(ambient.read_text()).is_equal_to("ambient runtime\n")


def test_embedded_hook_missing_tmpdir_fails_without_fallback(
    embedded_program: EmbeddedRunner,
    tmp_path: Path,
) -> None:
    """A missing isolation path cannot silently write into HOME or the cwd."""
    result = embedded_program("hook", ["ue"], "{}", {})
    assert_that(result.returncode).is_not_zero()
    assert_that((tmp_path / "probe-hook.log").exists()).is_false()
    assert_that((tmp_path / "home").exists()).is_false()


def test_embedded_mcp_requires_real_advertised_tool_call(
    embedded_program: EmbeddedRunner,
    tmp_path: Path,
) -> None:
    """Startup, discovery and ping never emit the invocation token."""
    log = tmp_path / "mcp.log"
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": "ping", "method": "ping"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
    ]
    result = embedded_program(
        "mcp",
        ["np", str(log)],
        "\n".join(map(json.dumps, messages)),
        {},
    )
    assert_that(result.returncode).is_zero()
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert_that([reply["id"] for reply in replies]).is_equal_to([1, "ping", 3])
    assert_that(replies[1]["result"]).is_equal_to({})
    tool = replies[-1]["result"]["tools"][0]
    assert_that(result.stdout).does_not_contain("PROBE-7f3a-integration")
    assert_that(log.read_text()).does_not_contain("called")
    messages.append(
        {
            "jsonrpc": "2.0",
            "id": "call",
            "method": "tools/call",
            "params": {"name": tool["name"], "arguments": {}},
        }
    )
    result = embedded_program(
        "mcp",
        ["np", str(log)],
        "\n".join(map(json.dumps, messages)),
        {},
    )
    assert_that(result.returncode).is_zero()
    assert_that(
        json.loads(result.stdout.splitlines()[-1])["result"]["content"]
    ).is_equal_to(
        [{"type": "text", "text": "PROBE-7f3a-integration-np"}],
    )
    assert_that(log.read_text()).contains("np called\n")


@pytest.mark.parametrize(
    "params",
    [
        None,
        [],
        {"name": "wrong"},
        {"name": "probe_integration_np", "arguments": []},
        {"name": "probe_integration_np", "arguments": {"extra": True}},
    ],
)
def test_embedded_mcp_invalid_calls_never_emit_token(
    embedded_program: EmbeddedRunner,
    tmp_path: Path,
    params: object,
) -> None:
    """Invalid calls cannot supply false integration invocation evidence."""
    log = tmp_path / "mcp.log"
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
    result = embedded_program("mcp", ["np", str(log)], json.dumps(request), {})
    assert_that(result.returncode).is_zero()
    assert_that(json.loads(result.stdout)["error"]["code"]).is_equal_to(-32602)
    assert_that(result.stdout).does_not_contain("PROBE-7f3a-integration")
    assert_that(log.read_text()).does_not_contain("called")


@pytest.mark.parametrize("request_id", [None, True, [], {}, float("nan"), float("inf")])
def test_embedded_mcp_rejects_invalid_ids(
    embedded_program: EmbeddedRunner,
    tmp_path: Path,
    request_id: object,
) -> None:
    """Malformed request identities cannot produce tool results or log invocations."""
    log = tmp_path / "mcp.log"
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": "probe_integration_np"},
    }
    result = embedded_program("mcp", ["np", str(log)], json.dumps(request), {})
    assert_that(result.returncode).is_zero()
    assert_that(result.stdout).is_empty()
    assert_that(log.read_text()).does_not_contain("called")


def test_report_sanitizes_private_notes_and_labels_fingerprint_scope(
    embedded_program: EmbeddedRunner,
    tmp_path: Path,
) -> None:
    """Returned JSON strips synthetic private paths/tokens and discloses diff limits."""
    rec = tmp_path / "records.jsonl"
    result_path = tmp_path / "results.json"
    home = str(tmp_path / "personal home")
    private_root = str(tmp_path / "private root")
    rec.write_text(
        json.dumps(
            {
                "note": f"{home}/settings {private_root}/log "
                "person@example.invalid github_pat_syntheticcredential "
                "eyJsynthetic.payload.signature"
            }
        )
        + "\n"
    )
    hook, mcp = tmp_path / "hook.log", tmp_path / "mcp.log"
    hook.write_text("PROBE-7f3a-lifecycle-ue sessionStart\n")
    mcp.write_text("ue started\n")
    (tmp_path / "removals.jsonl").write_text("")
    result = embedded_program(
        "report",
        [
            str(rec),
            str(result_path),
            "synthetic-version",
            "darwin-synthetic",
            "synthetic-os",
            "2",
            "0",
            str(hook),
            str(mcp),
            private_root,
            home,
            "complete",
            "",
            "complete",
            "",
            str(tmp_path / "removals.jsonl"),
            "0",
        ],
        "",
        {},
    )
    assert_that(result.returncode).is_zero()
    text = result_path.read_text()
    assert_that(text).does_not_contain(
        home,
        private_root,
        "person@example.invalid",
        "github_pat_synthetic",
        "eyJsynthetic",
    )
    report = json.loads(text)
    assert_that(report["interface"]).is_equal_to("ide")
    assert_that(report["policy"]).is_equal_to("none")
    assert_that(report["configComparisonScope"]).contains(
        "not distinct", "whole inventory"
    )
    assert_that(report["realConfigChangedEntries"]).is_equal_to(2)
    assert_that(report["checks"]).is_length(1)


@pytest.mark.parametrize("with_root", [False, True])
def test_snapshot_nounset_array_and_digest_only_in_disposable_home(
    tmp_path: Path,
    with_root: bool,
) -> None:
    """An empty root array is portable; existing synthetic files expose only digests."""
    source = SCRIPT.read_text()
    match = re.search(r"^snapshot\(\) \{\n.*?^\}", source, re.MULTILINE | re.DOTALL)
    if match is None:
        pytest.fail("Expected shell function is missing")
    function = match.group(0)
    # Modern Bash no longer fails on the old expansion; retain the 3.2 guard.
    assert_that(function).contains('${roots[@]+"${roots[@]}"}')
    if with_root:
        cursor = tmp_path / ".cursor"
        cursor.mkdir()
        (cursor / "settings.json").write_text("private synthetic settings")
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required for syntax and disposable function tests")
    result = subprocess.run(  # nosec B603 - extracted function, disposable HOME
        [bash, "--noprofile", "--norc", "-euc", function + "\nsnapshot"],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert_that(result.returncode).is_zero()
    assert_that(result.stderr).is_empty()
    assert_that(result.stdout).does_not_contain("private synthetic settings")
    if with_root:
        assert_that(result.stdout).contains("settings.json")
    else:
        assert_that(result.stdout).is_empty()


@pytest.mark.parametrize("keep", ["0", "1"])
def test_exit_cleanup_only_removes_owned_scratch(
    tmp_path: Path,
    keep: str,
) -> None:
    """Actual cleanup removes isolated logs or explicitly retains them with --keep."""
    match = re.search(
        r"^cleanup\(\) \{\n.*?^\}", SCRIPT.read_text(), re.MULTILINE | re.DOTALL
    )
    if match is None:
        pytest.fail("Expected shell function is missing")
    scratch = tmp_path / "owned"
    scratch.mkdir()
    (scratch / "probe-hook.log").write_text("owned\n")
    ambient = tmp_path / "probe-hook.log"
    ambient.write_text("ambient\n")
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required for syntax and disposable function tests")
    result = subprocess.run(  # nosec B603 - extracted cleanup, disposable paths
        [bash, "--noprofile", "--norc", "-euc", match.group(0) + "\ncleanup"],
        env={"ROOT": str(scratch), "KEEP": keep, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert_that(result.returncode).is_zero()
    assert_that(scratch.exists()).is_equal_to(keep == "1")
    assert_that(ambient.read_text()).is_equal_to("ambient\n")


def test_supplied_script_bash_syntax() -> None:
    """Parse the complete stock-Bash script without executing it."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required for syntax and disposable function tests")
    result = subprocess.run(  # nosec B603 - syntax-only Bash invocation
        [bash, "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert_that(result.returncode).is_zero()
    assert_that(result.stderr).is_empty()
