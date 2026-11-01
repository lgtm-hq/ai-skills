"""Collector boundary regressions: no network, firewall changes or real servers."""

from __future__ import annotations

import importlib
import json
import secrets
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from assertpy import assert_that

SPIKE = Path(__file__).resolve().parents[1] / "research/install-plane-spike"


@pytest.fixture
def collector(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, ModuleType]]:
    """Import collector modules from this checkout with reversible search paths.

    Args:
        monkeypatch: Reversible import path updates.

    Yields:
        Local stdlib collector modules.
    """
    monkeypatch.syspath_prepend(str(SPIKE / "scripts"))
    names = (
        "common",
        "network_control",
        "offline",
        "registry",
        "packages",
        "quarantine",
        "measure",
        "pins",
    )
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    try:
        modules = {
            "common": importlib.import_module("common"),
            "network_control": importlib.import_module("network_control"),
            "offline": importlib.import_module("offline"),
            "registry": importlib.import_module("registry"),
            "packages": importlib.import_module("packages"),
            "quarantine": importlib.import_module("quarantine"),
            "measure": importlib.import_module("measure"),
            "pins": importlib.import_module("pins"),
        }
        for module in modules.values():
            if module.__file__ is None:
                raise ValueError("collector module has no local source")
            assert_that(Path(module.__file__).resolve().is_relative_to(SPIKE)).is_true()
        yield modules
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


@pytest.mark.parametrize(
    "content", ['{"python":"3.14.6"}', '{\r\n  "python" : "3.14.6"\r\n}']
)
def test_pin_parser_accepts_json_layout(
    collector: dict[str, ModuleType], tmp_path: Path, content: str
) -> None:
    """Pin parsing tolerates CRLF and compact/reformatted JSON."""
    path = tmp_path / "settings.json"
    path.write_bytes(content.encode())
    assert_that(collector["pins"].python_pin(path)).is_equal_to("3.14.6")


def test_checkout_attributes_preserve_bytes(tmp_path: Path) -> None:
    """Git's effective attributes prevent CRLF conversion of exact fixture bytes."""
    import subprocess  # nosec B404 - read-only local git attribute query

    paths = [
        "fixtures/index.json",
        "fixtures/expected-output.json",
        "fixtures/artifact.tar",
        "scripts/pins.sh",
        "scripts/fixture.py",
    ]
    result = subprocess.run(  # nosec B603 - fixed local git arguments
        args=[
            "git",
            "-c",
            "core.autocrlf=true",
            "check-attr",
            "-z",
            "text",
            "eol",
            "--",
            *[f"research/install-plane-spike/{path}" for path in paths],
        ],
        cwd=SPIKE.parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    fields = result.stdout.rstrip("\0").split("\0")
    attributes = {
        (fields[i], fields[i + 1]): fields[i + 2] for i in range(0, len(fields), 3)
    }
    for path in paths[:3]:
        assert_that(
            attributes[(f"research/install-plane-spike/{path}", "text")]
        ).is_equal_to("unset")
    for path in paths[3:]:
        assert_that(
            attributes[(f"research/install-plane-spike/{path}", "eol")]
        ).is_equal_to("lf")


def probe_record(outcome: str, *, ipv6: str = "explicit-denial") -> dict[str, Any]:
    """Model network probe output without making a socket connection.

    Args:
        outcome: IPv4 observation.
        ipv6: Informational IPv6 observation.

    Returns:
        Command-shaped record for the shared endpoint.
    """
    return {
        "exit": 0,
        "stdout": json.dumps(
            [
                {"address": "1.1.1.1", "port": 443, "outcome": outcome},
                {"address": "2606:4700:4700::1111", "port": 443, "outcome": ipv6},
            ]
        ),
    }


@pytest.mark.parametrize(
    "before,after,expected",
    [
        ("connected", "explicit-denial", True),
        ("inconclusive", "explicit-denial", False),
        ("explicit-denial", "explicit-denial", False),
        ("connected", "inconclusive", False),
        ("connected", "connected", False),
    ],
)
def test_denial_requires_positive_ipv4_control(
    collector: dict[str, ModuleType], before: str, after: str, expected: bool
) -> None:
    """An unavailable IPv6 route or DROP timeout cannot manufacture a denial pass."""
    assert_that(
        collector["network_control"].proven_denial(
            control=probe_record(before),
            restricted=probe_record(after),
        )
    ).is_equal_to(expected)


def test_harden_runner_runs_directly_and_remains_unverified(
    collector: dict[str, ModuleType], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The empty-allowlist job adds no namespace and cannot invent its baseline."""
    calls: list[list[str]] = []

    def fake_command(**kwargs: Any) -> dict[str, Any]:
        """Model explicit denied probe and a successful offline worker.

        Args:
            kwargs: Collector command boundary arguments.

        Returns:
            Command observation; never launches a child process.
        """
        argv = kwargs["argv"]
        calls.append(argv)
        record = probe_record("explicit-denial")
        if "--worker" in argv:
            path = Path(argv[argv.index("--result") + 1])
            path.write_text(
                json.dumps({v: {"status": "pass"} for v in ("ts", "py")}),
                encoding="utf-8",
                newline="\n",
            )
        kwargs["records"].append(record)
        return record

    monkeypatch.setattr(collector["offline"], "command", fake_command)
    result = collector["offline"].measure_offline(
        build=tmp_path / "build", work=tmp_path, harden_block=True
    )
    assert_that(result["ts"]["status"]).is_equal_to("unverified")
    assert_that(result["ts"]["denial_proven"]).is_false()
    assert_that(result["ts"]["installation_observation"]["status"]).is_equal_to("pass")
    assert_that(any("unshare" in " ".join(argv) for argv in calls)).is_false()
    assert_that(calls).is_length(2)


@pytest.mark.parametrize(
    "stage,status,body",
    [
        ("account", 403, {"error": "account rejected"}),
        ("account", 201, None),
        ("account", 201, {}),
        ("account", 201, dict.fromkeys(["token"], 42)),
        ("account", 201, {"token": chr(32)}),
        ("account", 201, b"unreadable JSON"),
        ("account", 201, TimeoutError()),
        ("readiness", 503, {}),
        ("readiness", 200, TimeoutError()),
        ("kill-timeout", 403, {"error": "account rejected"}),
    ],
)
def test_registry_account_failure_is_sanitized_evidence(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    status: int,
    body: object,
) -> None:
    """Bad account responses retain both variant failures and server logs."""
    registry = collector["registry"]
    setup_temp = tmp_path / "trusted-setup-temp"
    collector["common"].write_json(
        path=tmp_path / "build/build.json",
        value={
            "registry_setup_environment": {
                key: str(setup_temp) for key in ("TMPDIR", "TEMP", "TMP")
            }
        },
    )
    monkeypatch.setattr(registry.time, "sleep", lambda _: None)
    password = secrets.token_urlsafe(24)
    monkeypatch.setattr(registry.secrets, "token_urlsafe", lambda _: password)
    requests: list[str] = []

    def response() -> SimpleNamespace:
        """Return a ready ping, then the selected account response.

        Returns:
            Fake HTTP response, including read timeout when requested.
        """
        ping = requests[-1] == "GET"

        def read() -> bytes:
            """Read the fake server body or raise a boundary timeout.

            Returns:
                Encoded JSON or malformed raw bytes.

            Raises:
                TimeoutError: If the selected account read times out.
            """
            if ping and stage != "readiness":
                return b"{}"
            if isinstance(body, TimeoutError):
                raise body
            return body if isinstance(body, bytes) else json.dumps(body).encode()

        return SimpleNamespace(
            status=200 if ping and stage != "readiness" else status, read=read
        )

    def request(**kwargs: Any) -> None:
        """Count HTTP operations without retaining credential-bearing bodies.

        Args:
            kwargs: Ignored request arguments except method.
        """
        requests.append(kwargs["method"])

    monkeypatch.setattr(
        registry.http.client,
        "HTTPConnection",
        lambda **_: SimpleNamespace(
            request=request, getresponse=response, close=lambda: None
        ),
    )
    # Prevent even the loopback port reservation from touching a socket.
    import contextlib

    monkeypatch.setattr(
        registry.socket,
        "socket",
        lambda: contextlib.nullcontext(
            SimpleNamespace(
                bind=lambda _: None, getsockname=lambda: ("127.0.0.1", 1234)
            )
        ),
    )
    monkeypatch.setattr(registry.shutil, "which", lambda _: "/fake/bun")

    def wait(**kwargs: Any) -> None:
        """Model a server that can fail both bounded shutdown waits.

        Args:
            kwargs: Wait timeout.

        Raises:
            TimeoutExpired: For the selected kill-timeout case.
        """
        if stage == "kill-timeout":
            raise registry.subprocess.TimeoutExpired("server", kwargs["timeout"])

    def popen(**kwargs: Any) -> SimpleNamespace:
        """Check server cache boundaries without treating this fake as startup proof.

        Args:
            kwargs: Server invocation and environment.

        Returns:
            Fake server process.
        """
        env = kwargs["env"]
        for key in ("TMPDIR", "TEMP", "TMP"):
            assert_that(env[key]).is_equal_to(str(setup_temp))
        assert_that(env["NPM_CONFIG_CACHE"]).starts_with(str(tmp_path / "server-env"))
        return SimpleNamespace(
            returncode=0,
            poll=lambda: None,
            terminate=lambda: None,
            kill=lambda: None,
            wait=wait,
        )

    monkeypatch.setattr(registry.subprocess, "Popen", popen)
    result = registry.measure_registry(build=tmp_path / "build", work=tmp_path)
    assert_that(result["ts"]["status"]).is_equal_to("fail")
    assert_that(result["py"]["status"]).is_equal_to("fail")
    assert_that(result["server"]).is_not_empty()
    assert_that(json.dumps(result)).does_not_contain(password)
    assert_that((tmp_path / "registry-evidence.json").is_file()).is_true()
    if stage == "kill-timeout":
        assert_that(result["server"][-1]["termination"]).contains("TimeoutExpired")


@pytest.mark.parametrize(
    "exit_code,text,enabled,expected",
    [
        (0, "Scan found no threats.", True, "clean"),
        (0, "Scan found no threats.", False, "unverified"),
        (2, "Threat detected", True, "threat"),
        (2, "service unavailable", True, "unverified"),
        (5, "engine failed", True, "unverified"),
        (None, "timeout", True, "unverified"),
    ],
)
def test_defender_engine_errors_are_not_threats(
    collector: dict[str, ModuleType],
    exit_code: int | None,
    text: str,
    enabled: bool,
    expected: str,
) -> None:
    """Clean/threat observations require engine health and matching scan output."""
    result = collector["quarantine"].defender_status(
        scan={"exit": exit_code, "stdout": text, "stderr": ""},
        engine={
            "exit": 0,
            "stdout": json.dumps(
                {"AMServiceEnabled": enabled, "AntivirusEnabled": enabled}
            ),
        },
    )
    assert_that(result).is_equal_to(expected)


def test_raw_evidence_export_needs_no_egress(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Raw JSON appears in both log and summary without an artifact service."""
    path, summary = tmp_path / "result.json", tmp_path / "summary.md"
    path.write_text('{"status":"unverified"}\n', encoding="utf-8", newline="\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    collector["common"].export_evidence(path)
    assert_that(capsys.readouterr().out).contains(path.read_text(encoding="utf-8"))
    assert_that(summary.read_text(encoding="utf-8")).contains(
        path.read_text(encoding="utf-8")
    )


def test_collector_failure_does_not_erase_other_scenarios(
    collector: dict[str, ModuleType], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even an unexpected registry error preserves completed offline/security JSON."""
    measure = collector["measure"]
    build, results = tmp_path / "build", tmp_path / "results"
    for variant in ("ts", "py"):
        (build / variant).mkdir(parents=True)
        (build / f"{variant}.tgz").write_bytes(b"test data")
    monkeypatch.setattr(
        measure, "command", lambda **_: {"stdout": "test-head", "exit": 0}
    )
    monkeypatch.setattr(
        measure,
        "measure_offline",
        lambda **_: {v: {"status": "unverified"} for v in ("ts", "py")},
    )
    monkeypatch.setattr(
        measure, "run_payload", lambda **_: {"status": "pass", "seconds": 0.01}
    )
    monkeypatch.setattr(
        measure, "measure_quarantine", lambda **_: {"status": "measured"}
    )

    def broken_registry(**kwargs: Any) -> None:
        """Inject an unexpected collector failure after checking saved evidence.

        Args:
            kwargs: Unused registry collection inputs.

        Raises:
            TimeoutError: Simulated account failure.
        """
        saved = json.loads(next(results.glob("*-ts.json")).read_text(encoding="utf-8"))
        assert_that(saved).contains_key("offline", "quarantine", "footprint")
        raise TimeoutError("test boundary")

    monkeypatch.setattr(measure, "measure_registry", broken_registry)
    monkeypatch.setattr(
        sys, "argv", ["measure.py", "--build", str(build), "--results", str(results)]
    )
    measure.main()
    saved = json.loads(next(results.glob("*-ts.json")).read_text(encoding="utf-8"))
    assert_that(saved["private_registry"]["collector_error"]).is_equal_to(
        "TimeoutError"
    )
    assert_that(saved["quarantine"]["status"]).is_equal_to("measured")


@pytest.mark.parametrize("cleanup_exit", [0, 1])
def test_firewall_is_scoped_and_cleanup_verified(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_exit: int,
) -> None:
    """Windows rules cannot block the runner and removal failures remain visible."""
    offline = collector["offline"]
    monkeypatch.setattr(
        offline, "worker", lambda **_: {v: {"status": "fail"} for v in ("ts", "py")}
    )
    monkeypatch.setattr(offline.platform, "system", lambda: "Windows")
    monkeypatch.setattr(offline.shutil, "which", lambda name: f"C:/{name}.exe")
    calls: list[list[str]] = []

    def fake_command(**kwargs: Any) -> dict[str, Any]:
        """Return boundary observations for probes, firewall and worker.

        Args:
            kwargs: Arguments for the command boundary.

        Returns:
            Explicit probe and cleanup results without executing PowerShell.
        """
        argv = kwargs["argv"]
        calls.append(argv)
        if argv[-1].endswith("network_control.py"):
            record = probe_record("connected" if len(calls) == 1 else "explicit-denial")
        elif "Remove-NetFirewallRule" in argv[-1]:
            record = {
                "exit": cleanup_exit,
                "stdout": "rules absent" if cleanup_exit == 0 else "",
                "stderr": "",
            }
        else:
            record = {"exit": 0, "stdout": "", "stderr": ""}
        kwargs["records"].append(record)
        return record

    monkeypatch.setattr(offline, "command", fake_command)
    observed = offline.measure_offline(build=tmp_path / "build", work=tmp_path)
    create = next(argv[-1] for argv in calls if "New-NetFirewallRule" in argv[-1])
    assert_that(create).contains("-Program $_")
    assert_that(any("Get-NetFirewallProfile" in argv[-1] for argv in calls)).is_true()
    assert_that(observed["ts"]["cleanup"]["status"]).is_equal_to(
        "verified removed" if cleanup_exit == 0 else "unverified removal"
    )
    assert_that(observed["ts"]["denial_proven"]).is_true()
    if cleanup_exit:
        assert_that(observed["ts"]["status"]).is_equal_to("unverified")


@pytest.mark.parametrize("mutation", ["none", "bytes", "platform"])
def test_package_client_checks_installed_bytes(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    """Successful install/stdout cannot hide missing or changed transported files."""
    import shutil

    packages = collector["packages"]
    source = tmp_path / "build/ts"
    source.mkdir(parents=True)
    (source / "spike").write_bytes(b"compiled payload stand-in")
    client = tmp_path / "client"
    monkeypatch.setattr(packages.shutil, "which", lambda _: "/fake/bun")
    monkeypatch.setattr(packages, "run_payload", lambda **_: {"status": "pass"})

    def install(**kwargs: Any) -> dict[str, Any]:
        """Copy package bytes and optionally model transport corruption.

        Args:
            kwargs: Explicit installer command inputs.

        Returns:
            A successful installer command record.
        """
        assert_that(kwargs["argv"]).contains("--ignore-scripts", "--offline")
        env = kwargs["env"]
        assert_that(Path(env["BUN_INSTALL_CACHE_DIR"]).exists()).is_false()
        assert_that(Path(env["NPM_CONFIG_CACHE"]).exists()).is_false()
        payload = (
            client
            / "node_modules"
            / f"@spike/ts-{collector['common'].target()}"
            / "payload"
        )
        shutil.copytree(src=source, dst=payload)
        if mutation == "bytes":
            (payload / "spike").write_bytes(b"changed payload")
        if mutation == "platform":
            other = next(
                item
                for item in packages.SETTINGS["targets"]
                if item != collector["common"].target()
            )
            (client / "node_modules" / f"@spike/ts-{other}").mkdir()
        return {"exit": 0}

    monkeypatch.setattr(packages, "command", install)
    observed = packages.install_client(
        build=source.parent,
        client=client,
        variant="ts",
        tool="bun",
        dependency="file:/local/wrapper.tgz",
        registry="http://127.0.0.1:9",
        offline=True,
    )
    assert_that(observed["payload_matches_build"]).is_equal_to(mutation != "bytes")
    assert_that(observed["status"]).is_equal_to(
        "pass" if mutation == "none" else "fail"
    )


@pytest.mark.parametrize("execution_status", ["pass", "fail"])
def test_disabled_gatekeeper_cannot_prove_enforcement(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    execution_status: str,
) -> None:
    """Attribute and CLI success remain unverified when Gatekeeper is disabled."""
    quarantine = collector["quarantine"]
    monkeypatch.setattr(quarantine.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(quarantine.shutil, "which", lambda name: f"/fake/{name}")
    monkeypatch.setattr(
        quarantine, "run_payload", lambda **_: {"status": execution_status}
    )
    calls = []

    def command(**kwargs: Any) -> dict[str, Any]:
        """Model a disabled Gatekeeper with otherwise successful commands.

        Args:
            kwargs: Explicit native assessment arguments.

        Returns:
            Successful command with disabled status when queried.
        """
        calls.append(kwargs["argv"])
        return {
            "exit": 0,
            "stdout": "assessments disabled" if "--status" in kwargs["argv"] else "",
        }

    monkeypatch.setattr(quarantine, "command", command)
    observed = quarantine.measure_quarantine(
        root=tmp_path, variant="ts", home=tmp_path / "home"
    )
    assert_that(observed["status"]).is_equal_to(
        "unverified" if execution_status == "pass" else "fail"
    )
    assert_that(observed["execution_status"]).is_equal_to(execution_status)
    assert_that(observed["security_enforcement"]).starts_with("unverified")
    assert_that(any("--status" in argv for argv in calls)).is_true()


def test_network_probe_uses_socket_boundary_fakes(
    collector: dict[str, ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unavailable IPv6 and IPv4 timeout stay inconclusive without real networking."""
    import contextlib
    import errno

    network = collector["network_control"]

    def socket(*, family: int) -> Any:
        """Supply a socket-shaped boundary fake for each protocol family.

        Args:
            family: Selected socket family.

        Returns:
            Context-managed fake that never opens a socket.
        """

        def connect(address: object) -> None:
            """Model timeout or missing IPv6 interface.

            Args:
                address: Unused remote address.

            Raises:
                TimeoutError: For IPv4 DROP behavior.
                OSError: For unavailable IPv6.
            """
            if family == network.socket.AF_INET:
                raise TimeoutError("DROP")
            raise OSError(errno.EADDRNOTAVAIL, "IPv6 unavailable")

        return contextlib.nullcontext(
            SimpleNamespace(settimeout=lambda _: None, connect=connect)
        )

    monkeypatch.setattr(network.socket, "socket", socket)
    observed = network.probe()
    assert_that([item["outcome"] for item in observed]).is_equal_to(
        ["inconclusive", "inconclusive"]
    )
    assert_that(observed[1]["informational"]).is_true()


def test_no_node_environment_retains_windows_loader_control(
    collector: dict[str, ModuleType], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remove Node/Bun directories while preserving required Windows variables."""
    tools, clean = tmp_path / "tools", tmp_path / "clean"
    tools.mkdir()
    clean.mkdir()
    (tools / "node.exe").write_bytes(b"not executable")
    monkeypatch.setenv("PATH", str(tools) + collector["common"].os.pathsep + str(clean))
    monkeypatch.setenv("SYSTEMDRIVE", "C:")
    monkeypatch.setenv("PATHEXT", ".EXE;.CMD")
    observed = collector["common"].isolated_env(tmp_path / "home")
    assert_that(observed["PATH"]).is_equal_to(str(clean))
    assert_that(observed["SYSTEMDRIVE"]).is_equal_to("C:")
    assert_that(observed["PATHEXT"]).is_equal_to(".EXE;.CMD")
    assert_that(observed["APPDATA"]).starts_with(str(tmp_path / "home"))


def test_command_redacts_before_persistence_or_display(
    collector: dict[str, ModuleType], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ephemeral publication credentials cannot appear in command evidence/logs."""
    credential = secrets.token_urlsafe(24)
    records: list[dict[str, Any]] = []
    result = collector["common"].command(
        argv=[
            sys.executable,
            "-I",
            "-c",
            "import os; print(os.environ['SPIKE_SAMPLE'])",
        ],
        env={**collector["common"].isolated_env(tmp_path), "SPIKE_SAMPLE": credential},
        cwd=tmp_path,
        records=records,
        redactions=(credential,),
    )
    assert_that(result["exit"]).is_zero()
    assert_that(result["stdout"]).contains("[redacted]")
    assert_that(json.dumps(records) + capsys.readouterr().out).does_not_contain(
        credential
    )


@pytest.mark.parametrize("output", [b"partial\xff", "partial text", None])
def test_timeout_output_is_retained(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: str | bytes | None,
) -> None:
    """Timeouts accept both subprocess output types and remain failed observations."""
    common = collector["common"]

    def timeout(**kwargs: Any) -> None:
        """Model a command timeout without starting a child.

        Args:
            kwargs: Ignored process arguments.

        Raises:
            TimeoutExpired: With partial text or bytes.
        """
        raise common.subprocess.TimeoutExpired("fake", 1, output=output, stderr=output)

    monkeypatch.setattr(common.subprocess, "Popen", timeout)
    observed = common.command(argv=["fake"], cwd=tmp_path, records=[])
    assert_that(observed["exit"]).is_none()
    assert_that(observed["error"]).is_equal_to("timeout")
    assert_that(observed["stdout"]).is_equal_to(common.output_text(output))


def test_command_timeout_terminates_descendants(
    collector: dict[str, ModuleType],
    tmp_path: Path,
) -> None:
    """A child retaining pipe handles cannot make a timed-out command hang."""
    result = collector["common"].command(
        argv=[
            sys.executable,
            "-I",
            "-c",
            (
                "import subprocess,sys,time; "
                "subprocess.Popen([sys.executable,'-c',"
                "'import time; time.sleep(30)']); "
                "print('started',flush=True); time.sleep(30)"
            ),
        ],
        cwd=tmp_path,
        records=[],
        timeout=1,
    )
    assert_that(result["error"]).is_equal_to("timeout")
    assert_that(result["stdout"]).contains("started")
    assert_that(result["seconds"]).is_less_than(15)


def test_namespace_fallback_restores_environment_after_dropping_identity(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sudo only sets up netns; probes and workers use the original unprivileged UID."""
    offline = collector["offline"]
    monkeypatch.setattr(offline.platform, "system", lambda: "Linux")
    monkeypatch.setattr(offline.shutil, "which", lambda name: f"/setup/{name}")
    monkeypatch.setattr(offline.os, "getuid", lambda: 1234, raising=False)
    monkeypatch.setattr(offline.os, "geteuid", lambda: 1234, raising=False)
    monkeypatch.setattr(offline.os, "getgid", lambda: 5678, raising=False)
    monkeypatch.setattr(
        offline,
        "worker",
        lambda **_: {
            v: {
                "status": "fail",
                "clients": {"bun": {"status": "fail"}, "npm": {"status": "pass"}},
            }
            for v in ("ts", "py")
        },
    )
    calls: list[dict[str, Any]] = []

    def command(**kwargs: Any) -> dict[str, Any]:
        """Reject user namespaces, then model the privileged setup boundary.

        Args:
            kwargs: Probe or worker inputs.

        Returns:
            Successful baseline, explicit namespace denial, or worker JSON.
        """
        calls.append(kwargs)
        argv = kwargs["argv"]
        if "--worker" in argv:
            result = {
                v: {"status": "fail", "identity": {"effective_uid": 1234}}
                for v in ("ts", "py")
            }
            Path(argv[argv.index("--result") + 1]).write_text(
                json.dumps(result), encoding="utf-8"
            )
            return {"exit": 0}
        if "--user" in argv:
            return {"exit": 1, "stdout": ""}
        return probe_record("connected" if len(calls) == 1 else "explicit-denial")

    monkeypatch.setattr(offline, "command", command)
    observed = offline.measure_offline(build=tmp_path / "build", work=tmp_path)
    sudo_calls = [call for call in calls if call["argv"][0] == "/setup/sudo"]
    assert_that(sudo_calls).is_length(2)
    for call in sudo_calls:
        argv = call["argv"]
        assert_that(argv).contains(
            "--reuid", "1234", "--regid", "5678", "--clear-groups"
        )
        assignments = argv[argv.index("-i") + 1 :]
        assert_that(assignments).contains(
            *[f"{key}={value}" for key, value in call["env"].items()]
        )
        assert_that(argv.index("--reuid")).is_less_than(argv.index("-i"))
    assert_that(
        observed["ts"]["installation_observation"]["identity"]["effective_uid"]
    ).is_equal_to(1234)
    assert_that(observed["ts"]["positive_installation_control"]["status"]).is_equal_to(
        "fail"
    )
    assert_that(observed["ts"]["status"]).is_equal_to("fail")


def test_offline_worker_refuses_root(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A root worker must fail before packing or executing any package manager."""
    offline = collector["offline"]
    monkeypatch.setattr(offline, "identity", lambda: {"effective_uid": 0})
    with pytest.raises(ValueError, match="as root"):
        offline.worker(build=tmp_path, work=tmp_path)


def test_cleanup_failure_still_exports_evidence(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Cleanup errors remain errors while persisted JSON reaches log and summary."""
    import contextlib

    measure = collector["measure"]
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    work = tmp_path / "work"
    work.mkdir()

    @contextlib.contextmanager
    def temporary(**kwargs: Any) -> Iterator[str]:
        """Model the observed late cleanup failure without creating root files.

        Args:
            kwargs: Ignored tempdir options.

        Yields:
            Disposable local directory.

        Raises:
            PermissionError: After all scenario evidence is saved.
        """
        yield str(work)
        raise PermissionError("cleanup boundary")

    monkeypatch.setattr(measure.tempfile, "TemporaryDirectory", temporary)
    monkeypatch.setattr(measure, "command", lambda **_: {"stdout": "head", "exit": 0})
    monkeypatch.setattr(
        measure,
        "measure_offline",
        lambda **_: {v: {"status": "fail"} for v in ("ts", "py")},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "measure.py",
            "--offline-only",
            "--build",
            str(tmp_path / "build"),
            "--results",
            str(tmp_path / "results"),
        ],
    )
    with pytest.raises(PermissionError, match="cleanup boundary"):
        measure.main()
    output = capsys.readouterr().out
    for path in (tmp_path / "results").glob("*.json"):
        assert_that(output).contains(path.name)
        assert_that(summary.read_text(encoding="utf-8")).contains(path.name)
    assert_that(summary.read_text(encoding="utf-8")).contains(
        '"offline": {', '"status": "fail"'
    )


def test_json_evidence_has_utf8_and_lf_bytes(
    collector: dict[str, ModuleType],
    tmp_path: Path,
) -> None:
    """JSON output uses LF and retains Unicode independently of the Windows locale."""
    path = tmp_path / "result.json"
    collector["common"].write_json(path=path, value={"text": "\ufeffkeep"})
    assert_that(path.read_bytes()).does_not_contain(b"\r")
    assert_that(json.loads(path.read_bytes())["text"]).is_equal_to("\ufeffkeep")
