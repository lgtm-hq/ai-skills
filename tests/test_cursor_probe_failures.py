"""Exercise the actual interactive driver offline with fake macOS/IDE commands."""

import json
import shlex
import shutil
import subprocess  # nosec B404 - local driver with disposable HOME and fake tools
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that

SCRIPT = Path(__file__).parent / "fixtures/host-probe/cursor-macos-probe-driver.sh"
type DriverRunner = Callable[
    [str, bool], tuple[subprocess.CompletedProcess[str], dict[str, Any], Path]
]


@pytest.fixture
def driver(tmp_path: Path, request: pytest.FixtureRequest) -> DriverRunner:
    """Run the unchanged source driver; stub only OS/IDE tools in a synthetic HOME."""
    bash = shutil.which("bash")
    real_find = shutil.which("find")
    real_shasum = shutil.which("shasum")
    real_diff = shutil.which("diff")
    if bash is None or real_find is None or real_shasum is None or real_diff is None:
        pytest.skip("Offline driver requires Bash and standard file tools")
    home = tmp_path / "personal home"
    config = home / ".cursor/settings.json"
    config.parent.mkdir(parents=True)
    config.write_text("private synthetic configuration\n")
    scratch = tmp_path / getattr(request, "param", "scratch")
    scratch.mkdir()
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "python3").symlink_to(sys.executable)
    app = home / "Applications/Cursor.app"
    cli = app / "Contents/Resources/app/bin/cursor"
    cli.parent.mkdir(parents=True)

    def run(
        failure: str,
        keep: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, Any], Path]:
        """Inject failures at real collection calls in the unchanged driver."""
        fake = tools / "fake"
        fake.write_text(
            f"#!{sys.executable}\n"
            "import json, os, signal, subprocess, sys\n"
            "from pathlib import Path\n"
            f"base = Path({str(tmp_path)!r})\n"
            f"failure = {failure!r}\n"
            f"real_find = {real_find!r}\n"
            f"real_shasum = {real_shasum!r}\n"
            f"real_diff = {real_diff!r}\n"
            "name = Path(sys.argv[0]).name\n"
            "marker = base / 'running'\n"
            "if name == 'uname':\n"
            "    print('Darwin' if sys.argv[1] == '-s' else 'synthetic')\n"
            "elif name == 'sw_vers':\n"
            "    print('synthetic-os')\n"
            "elif name == 'security':\n"
            "    state = base / 'keychains.json'\n"
            "    original = [] if failure == 'empty-keychains' else [\n"
            "        '/synthetic/login keychain-db', '/synthetic/other.keychain-db']\n"
            "    chains = (json.loads(state.read_text())\n"
            "              if state.exists() else original)\n"
            "    if sys.argv[1] == 'list-keychains':\n"
            "        if '-s' in sys.argv:\n"
            "            chains = sys.argv[sys.argv.index('-s') + 1:]\n"
            "        else:\n"
            "            for chain in chains:\n"
            "                print('    ' + json.dumps(chain))\n"
            "    elif sys.argv[1] == 'create-keychain':\n"
            "        chains.append(sys.argv[-1])\n"
            "    elif sys.argv[1] == 'delete-keychain':\n"
            "        chains = [chain for chain in chains if chain != sys.argv[-1]]\n"
            "    state.write_text(json.dumps(chains))\n"
            "elif name == 'pgrep':\n"
            "    remaining = int(marker.read_text()) if marker.exists() else 0\n"
            "    if remaining:\n"
            "        marker.write_text(str(remaining - 1))\n"
            "    sys.exit(0 if remaining else 1)\n"
            "elif name == 'pkill':\n"
            "    marker.unlink(missing_ok=True)\n"
            "elif name == 'cursor':\n"
            "    marker.write_text('2')\n"
            "    home = Path(os.environ['HOME'])\n"
            "    root = home.parent\n"
            "    (home / '.cursor').mkdir(exist_ok=True)\n"
            "    (home / '.cursor/argv.json').write_text('{}')\n"
            "    counter = base / 'launches'\n"
            "    phase = int(counter.read_text()) + 1 if counter.exists() else 1\n"
            "    counter.write_text(str(phase))\n"
            "    if phase <= 4:\n"
            "        tag = ['ue', 'rm', 'np', 'npp'][phase - 1]\n"
            "        if failure in ('serialize-hooks', 'serialize-mcp'):\n"
            "            config_root = [home / '.cursor',\n"
            "                root / 'project/.cursor',\n"
            "                home / '.cursor/plugins/local/probe-sentinel-np',\n"
            "                root / 'project/.cursor/plugins/local/"
            "probe-sentinel-npp'][phase - 1]\n"
            "            writer = failure.removeprefix('serialize-')\n"
            "            relative = ('hooks/hooks.json' if phase >= 3\n"
            "                        else 'hooks.json') if writer == 'hooks' "
            "else 'mcp.json'\n"
            "            config = json.loads((config_root / relative).read_text())\n"
            "            executions = []\n"
            "            if writer == 'hooks':\n"
            "                for event, hooks in config['hooks'].items():\n"
            "                    for hook in hooks:\n"
            "                        data = {'hook_event_name': event}\n"
            "                        completed = subprocess.run(\n"
            "                            ['/bin/sh', '-c', hook['command']],\n"
            "                            input=json.dumps(data),\n"
            "                            text=True, capture_output=True,\n"
            "                            check=True, timeout=5)\n"
            "                        executions.append(json.loads(completed.stdout))\n"
            "            (base / f'{writer}-{tag}.json').write_text(json.dumps({\n"
            "                'root': str(root), 'config': config,\n"
            "                'executions': executions}))\n"
            "        with (root / 'tmp/probe-hook.log').open('a') as stream:\n"
            "            stream.write(f'PROBE-7f3a-lifecycle-{tag} sessionStart\\n')\n"
            "            if phase == 4 and failure == 'stale-hook':\n"
            "                stream.write('PROBE-7f3a-lifecycle-np "
            "beforeSubmitPrompt\\n')\n"
            "        with (root / 'logs/mcp.log').open('a') as stream:\n"
            "            stream.write(f'{tag} started\\n')\n"
            "    if phase == 5 and failure == 'report-record':\n"
            "        with (root / 'logs/records.jsonl').open('a') as stream:\n"
            "            stream.write('{truncated\\n')\n"
            "    if phase == 5 and failure == 'report-read':\n"
            "        log = root / 'logs/mcp.log'\n"
            "        log.unlink()\n"
            "        log.mkdir()\n"
            "elif name == 'shasum':\n"
            "    counter = base / 'snapshots'\n"
            "    count = int(counter.read_text()) + 1 if counter.exists() else 1\n"
            "    counter.write_text(str(count))\n"
            "    if count == 2 and failure == 'snapshot-read':\n"
            "        sys.exit(1)\n"
            "    if count == 2 and failure == 'snapshot-disappear':\n"
            "        Path(sys.argv[-1]).unlink()\n"
            "    os.execv(real_shasum, [real_shasum, *sys.argv[1:]])\n"
            "elif name == 'diff':\n"
            "    if failure == 'diff':\n"
            "        sys.exit(2)\n"
            "    if failure == 'interrupt':\n"
            "        os.kill(os.getppid(), signal.SIGTERM)\n"
            "        sys.exit(1)\n"
            "    os.execv(real_diff, [real_diff, *sys.argv[1:]])\n"
            "elif name == 'find':\n"
            "    if (failure == 'report-find'\n"
            "            and 'ai-skills-563-cursor.' in sys.argv[1]):\n"
            "        sys.exit(1)\n"
            "    os.execv(real_find, [real_find, *sys.argv[1:]])\n",
            encoding="utf-8",
        )
        fake.chmod(0o700)
        for name in (
            "uname",
            "sw_vers",
            "security",
            "pgrep",
            "pkill",
            "find",
            "shasum",
            "diff",
        ):
            (tools / name).symlink_to(fake)
        # The fake IDE exits after startup verification; no real wait is needed.
        sleep = tools / "sleep"
        sleep.write_text("#!/bin/sh\nexit 0\n")
        sleep.chmod(0o700)
        cli.symlink_to(fake)
        note = f"{home}/private github_pat_syntheticcredential person@example.invalid"
        result = subprocess.run(  # nosec B603 - fixed local driver, fake IDE, disposable HOME
            [bash, str(SCRIPT.resolve()), *(["--keep"] if keep else [])],
            input=(f"\ny\n{note}\n" * 100),
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={
                "HOME": str(home),
                "TMPDIR": str(scratch),
                "PATH": f"{tools}:/usr/bin:/bin",
                "CURSOR_PROBE_APP": str(app),
            },
            timeout=60,
            check=False,
        )
        outputs = list(tmp_path.glob("cursor-probe-results-*.json"))
        assert_that(outputs).described_as(result.stderr).is_length(1)
        text = outputs[0].read_text()
        assert_that(text).does_not_contain(
            str(home),
            "github_pat_synthetic",
            "person@example.invalid",
            "private synthetic configuration",
        )
        return result, json.loads(text), scratch

    return run


@pytest.mark.parametrize(
    "driver",
    [
        "scratch with spaces",
        "scratch'apostrophe",
        'scratch"doublequote',
        r"scratch\backslash",
        "scratch mixed '\"\\ chars",
    ],
    ids=["spaces", "apostrophe", "doublequote", "backslash", "mixed"],
    indirect=True,
)
@pytest.mark.parametrize("writer", ["hooks", "mcp"])
def test_driver_serializes_scratch_paths(
    driver: DriverRunner,
    writer: str,
) -> None:
    """Real writers preserve argv; generated hooks execute in the fake IDE only."""
    result, report, scratch = driver(f"serialize-{writer}", False)
    assert_that(result.returncode).described_as(result.stderr).is_zero()
    for tag in ("ue", "rm", "np", "npp"):
        captured = scratch.parent / f"{writer}-{tag}.json"
        assert_that(captured.exists()).described_as(
            f"Fake app failed to consume {writer} config for {tag}",
        ).is_true()
        payload = json.loads(captured.read_text())
        root = Path(payload["root"])
        assert_that(root.parent).is_equal_to(scratch.resolve())
        config = payload["config"]
        if writer == "mcp":
            assert_that(config["mcpServers"]).is_equal_to(
                {
                    f"probe-{tag}": {
                        "command": "python3",
                        "args": [
                            str(root / "sentinels/mcp.py"),
                            tag,
                            str(root / "logs/mcp.log"),
                        ],
                    },
                },
            )
        else:
            assert_that(config["version"]).is_equal_to(1)
            assert_that(config["hooks"]).contains_only(
                "sessionStart",
                "beforeSubmitPrompt",
            )
            for event, hooks in config["hooks"].items():
                assert_that(hooks).is_length(1)
                assert_that(shlex.split(hooks[0]["command"])).is_equal_to(
                    ["python3", str(root / "sentinels/hook.py"), tag],
                )
                assert_that(report["hookLog"]).contains(
                    f"PROBE-7f3a-lifecycle-{tag} {event}",
                )
            assert_that(payload["executions"]).is_equal_to([{}, {}])
    assert_that(list(scratch.iterdir())).is_empty()


@pytest.mark.parametrize("failure", ["none", "empty-keychains"])
def test_driver_restores_exact_keychain_search_list(
    driver: DriverRunner,
    failure: str,
) -> None:
    """Keychain restoration preserves an empty list and paths containing spaces."""
    result, report, scratch = driver(failure, False)
    assert_that(result.returncode).described_as(result.stderr).is_zero()
    expected = (
        []
        if failure == "empty-keychains"
        else ["/synthetic/login keychain-db", "/synthetic/other.keychain-db"]
    )
    assert_that(
        json.loads((scratch.parent / "keychains.json").read_text())
    ).is_equal_to(
        expected,
    )
    assert_that(report["cleanup"]["status"]).is_equal_to("purged")
    assert_that(list(scratch.iterdir())).is_empty()


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        ("snapshot-read", "final-snapshot-failed"),
        ("snapshot-disappear", "final-snapshot-failed"),
        ("diff", "config-diff-failed"),
        ("report-find", "report-collection-failed"),
        ("report-record", "report-collection-incomplete"),
        ("report-read", "report-collection-incomplete"),
        ("interrupt", "interrupted-term"),
    ],
)
def test_driver_saves_partial_answers_before_default_purge(
    driver: DriverRunner,
    failure: str,
    reason: str,
) -> None:
    """Real failures preserve completed human/automatic checks and available logs."""
    result, report, scratch = driver(failure, False)
    assert_that(result.returncode).is_not_zero()
    assert_that(report["runStatus"]).is_equal_to("incomplete")
    assert_that(report["incompleteReason"]).described_as(
        result.stderr + result.stdout[-1500:]
    ).is_equal_to(reason)
    assert_that(report["configComparisonStatus"]).is_equal_to("unverified")
    assert_that(report["configComparisonReason"]).is_not_empty()
    assert_that(report["realConfigChangedEntries"]).is_none()
    assert_that(report["checks"]).is_not_empty()
    assert_that(report["checks"][0]["check"]).is_equal_to("ue-skill")
    assert_that(report["checks"][0]["answer"]).is_equal_to("y")
    assert_that(report["checks"][-1]["check"]).is_equal_to("final-clean")
    assert_that(report["hookLog"]).is_not_empty()
    if failure != "report-read":
        assert_that(report["mcpLog"]).is_not_empty()
    assert_that(report["cleanup"]).is_equal_to({"mode": "purge", "status": "purged"})
    assert_that(list(scratch.iterdir())).is_empty()


def test_driver_keep_preserves_private_scratch_and_partial_json(
    driver: DriverRunner,
) -> None:
    """--keep explicitly retains private state without claiming a purge."""
    result, report, scratch = driver("snapshot-read", True)
    assert_that(result.returncode).is_not_zero()
    assert_that(report["runStatus"]).is_equal_to("incomplete")
    assert_that(report["cleanup"]).is_equal_to({"mode": "keep", "status": "retained"})
    roots = list(scratch.iterdir())
    assert_that(roots).is_length(1)
    assert_that((roots[0] / "logs/records.jsonl").exists()).is_true()
    assert_that((roots[0] / "logs/real-before.txt").exists()).is_true()


@pytest.mark.parametrize("failure", ["none", "stale-hook"])
def test_driver_hook_removal_uses_restart_boundary_and_exact_tag(
    driver: DriverRunner,
    failure: str,
) -> None:
    """Old np events and new npp events pass; a new removed np event fails removal."""
    result, report, scratch = driver(failure, False)
    assert_that(result.returncode).is_zero()
    assert_that(report["runStatus"]).is_equal_to("complete")
    assert_that(report["configComparisonStatus"]).is_equal_to("complete")
    assert_that(report["realConfigChangedEntries"]).is_zero()
    assert_that(report["hookLog"]).contains(
        "PROBE-7f3a-lifecycle-np sessionStart",
        "PROBE-7f3a-lifecycle-npp sessionStart",
    )
    boundaries = [
        event
        for event in report["hookRemovalEvidence"]
        if event["phase"] == "before-removal-restart"
    ]
    removals = [
        event
        for event in report["hookRemovalEvidence"]
        if event["phase"] == "after-restart-fresh-prompt"
    ]
    assert_that(boundaries).is_length(4)
    assert_that(removals).is_length(4)
    for before, after in zip(boundaries, removals, strict=True):
        assert_that(after["byteBoundary"]).is_equal_to(
            before["byteBoundary"]
        ).is_greater_than(0)
        assert_that(after["lineBoundary"]).is_equal_to(
            before["lineBoundary"]
        ).is_greater_than(0)
        expected = (
            "still-firing"
            if failure == "stale-hook" and after["tag"] == "np"
            else "verified-absent"
        )
        assert_that(after["status"]).is_equal_to(expected)
    check = next(
        check for check in report["checks"] if check["check"] == "np-lifecycle-removed"
    )
    assert_that(check["answer"]).is_equal_to("n" if failure == "stale-hook" else "y")
    assert_that(list(scratch.iterdir())).is_empty()
