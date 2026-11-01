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
    # Tests opt into hosted identity explicitly; CI's own run must not leak in.
    for key in (
        "GITHUB_ACTIONS",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_STEP_SUMMARY",
        "SPIKE_SOURCE_SHA",
    ):
        monkeypatch.delenv(key, raising=False)
    names = (
        "common",
        "network_control",
        "offline",
        "registry",
        "packages",
        "quarantine",
        "measure",
        "pins",
        "process_tree",
        "windows_job",
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
            "process_tree": importlib.import_module("process_tree"),
            "windows_job": importlib.import_module("windows_job"),
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
    assert_that(result["ts"]["probe_denial_proven"]).is_false()
    assert_that(result["ts"]["installer_denial_proven"]).is_false()
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
                if requests.count("GET") == 1:
                    raise ConnectionRefusedError("startup pending")
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
    monkeypatch.setattr(registry, "command", lambda **_: {"exit": 0})
    monkeypatch.setattr(
        registry,
        "stop_process_tree",
        lambda _: {
            "status": "unverified" if stage == "kill-timeout" else "pass",
            "error": "TimeoutExpired" if stage == "kill-timeout" else None,
        },
    )

    def wait(**kwargs: Any) -> None:
        """Model a server that can fail both bounded shutdown waits.

        Args:
            kwargs: Wait timeout.

        Raises:
            TimeoutExpired: For the selected kill-timeout case.
        """
        if stage == "kill-timeout":
            raise collector["process_tree"].subprocess.TimeoutExpired(
                "server", kwargs["timeout"]
            )

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
            pid=99999999,
            returncode=0,
            poll=lambda: None,
            terminate=lambda: None,
            kill=lambda: None,
            wait=wait,
        )

    monkeypatch.setattr(registry, "launch_process", popen)
    result = registry.measure_registry(build=tmp_path / "build", work=tmp_path)
    for variant in ("ts", "py"):
        assert_that(result[variant]["status"]).is_equal_to("fail")
    assert_that(result["server"]).is_not_empty()
    assert_that(json.dumps(result)).does_not_contain(password)
    assert_that((tmp_path / "registry-evidence.json").is_file()).is_true()
    if stage != "readiness":
        ready = next(
            item
            for item in result["server"]
            if item.get("operation") == "registry readiness"
        )
        assert_that(ready).does_not_contain_key("error")
    if stage == "kill-timeout":
        assert_that(result["server"][-1]["termination"]["error"]).is_equal_to(
            "TimeoutExpired"
        )


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
    monkeypatch.setenv("SPIKE_SOURCE_SHA", "test-head")
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
@pytest.mark.parametrize("setup_exit", [0, 1])
@pytest.mark.parametrize("bun_status", ["pass", "fail"])
def test_firewall_is_scoped_and_cleanup_verified(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_exit: int,
    setup_exit: int,
    bun_status: str,
) -> None:
    """Python-only denial cannot certify either successful installer as offline."""
    offline = collector["offline"]
    installs = {
        v: {
            "status": bun_status,
            "clients": {"bun": {"status": bun_status}, "npm": {"status": "pass"}},
        }
        for v in ("ts", "py")
    }
    monkeypatch.setattr(offline, "worker", lambda **_: installs)
    monkeypatch.setattr(offline.platform, "system", lambda: "Windows")
    monkeypatch.setattr(offline.shutil, "which", lambda name: f"C:/{name}.exe")
    monkeypatch.setattr(
        offline,
        "runtime",
        lambda *, root, variant: [
            f"C:/spike/{root.relative_to(root.anchor).as_posix()}/"
            + ("runtime/python.exe" if variant == "py" else "spike.exe")
        ],
    )
    monkeypatch.setattr(
        offline, "firewall_program", lambda path: {"program": str(path)}
    )
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
        elif "New-NetFirewallRule" in argv[-1]:
            record = {
                "exit": setup_exit,
                "stdout": "one rule created",
                "stderr": (
                    "Windows System Error 87,New-NetFirewallRule" if setup_exit else ""
                ),
            }
        elif "--worker" in argv:
            Path(argv[argv.index("--result") + 1]).write_text(
                json.dumps(installs), encoding="utf-8"
            )
            record = {"exit": 0, "stdout": "", "stderr": ""}
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
    for variant in ("ts", "py"):
        assert_that(observed[variant]["probe_denial_proven"]).is_equal_to(
            setup_exit == 0
        )
        assert_that(observed[variant]["installer_denial_proven"]).is_false()
        assert_that(observed[variant]["status"]).is_equal_to("unverified")
        assert_that(observed[variant]).does_not_contain_key("denial_proven")
        if setup_exit == 0:
            assert_that(observed[variant]["denial_scope"]).contains("Python probe only")
            assert_that(observed[variant]["installation_observation"]).is_equal_to(
                installs[variant]
            )
    assert_that(create).contains(str(Path("C:/bun.exe")), str(Path("C:/node.exe")))
    assert_that(create).does_not_contain("Runner.Worker", "0.0.0.0/0")
    if setup_exit:
        assert_that(observed["ts"]["status"]).is_equal_to("unverified")
        assert_that(any("--worker" in argv for argv in calls)).is_false()
        assert_that(observed["ts"]).does_not_contain_key("restricted_probe")
        if cleanup_exit == 0:
            assert_that(observed["ts"]["reason"]).contains(
                "Windows System Error 87", "exit 1"
            )
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

    monkeypatch.setattr(common, "launch_process", timeout)
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


def test_exited_parent_with_inherited_pipes_is_cleaned(
    collector: dict[str, ModuleType],
    tmp_path: Path,
) -> None:
    """Hosted Windows smoke: an exited root cannot orphan a pipe-holding child."""
    result = collector["common"].command(
        argv=[
            sys.executable,
            "-I",
            "-c",
            (
                "import subprocess,sys; "
                "subprocess.Popen([sys.executable,'-I','-c',"
                "'import time; print(\"child ready\",flush=True); time.sleep(30)']); "
                "print('parent exiting',flush=True)"
            ),
        ],
        cwd=tmp_path,
        records=[],
        timeout=2,
    )
    assert_that(result["error"]).is_equal_to("timeout")
    assert_that(result["stdout"]).contains("parent exiting", "child ready")
    assert_that(result).does_not_contain_key("termination_error")
    assert_that(result["seconds"]).is_less_than(10)
    if sys.platform == "win32":
        cleanup = result["tree_termination"]
        assert_that(cleanup["status"]).described_as(str(cleanup)).is_equal_to("pass")
        assert_that(cleanup["active_processes"]).is_zero()
        assert_that(cleanup["exit"]).is_zero()  # Root exited before job termination.
        assert_that(cleanup["job_handle_closed"]).is_true()


@pytest.mark.parametrize("stage", ["success", "create", "assign", "resume"])
def test_windows_suspended_launch_lifecycle(
    collector: dict[str, ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    """Assignment precedes execution; failures terminate/reap the suspended root."""
    module = collector["windows_job"]
    calls: list[str] = []

    def create(*args: Any) -> tuple[int, int, int, int]:
        """Return retained handles for a suspended root, without executing code."""
        assert_that(args[5]).is_equal_to(4)
        assert_that(args[4]).is_true()
        assert_that(args[-1].lpAttributeList["handle_list"]).is_equal_to([11, 12, 13])
        calls.append("create suspended")
        if stage == "create":
            raise OSError("create rejected")
        return 101, 102, 103, 104

    def operation(name: str, *args: Any) -> None:
        """Record a handle operation, optionally rejecting ownership or resume."""
        calls.append(name)
        if name == stage:
            raise OSError(name + " rejected")

    def wait_root(*args: Any) -> int:
        """Observe bounded reap through the retained root handle."""
        calls.append("wait root")
        return 0

    native = SimpleNamespace(
        STARTF_USESTDHANDLES=256,
        WAIT_OBJECT_0=0,
        CreateProcess=create,
        TerminateProcess=lambda *args: operation("terminate root", *args),
        WaitForSingleObject=wait_root,
        CloseHandle=lambda handle: calls.append("close " + str(handle)),
    )
    monkeypatch.setitem(sys.modules, "_winapi", native)
    monkeypatch.setattr(
        module.subprocess,
        "STARTUPINFO",
        lambda: SimpleNamespace(dwFlags=0),
        raising=False,
    )
    monkeypatch.setattr(module.subprocess, "Handle", lambda hp: hp, raising=False)
    root = SimpleNamespace(
        job=SimpleNamespace(
            assign=lambda hp: operation("assign", hp),
            resume=lambda ht: operation("resume", ht),
        ),
        _filter_handle_list=lambda handles: handles,
        _close_pipe_fds=lambda *args: calls.append("close child pipes"),
    )

    def launch() -> None:
        """Exercise the real adapter with mocked native OS calls."""
        module.JobPopen._execute_child(
            root,
            ["owned.exe"],
            None,
            None,
            True,
            (),
            None,
            {},
            None,
            0,
            False,
            11,
            21,
            22,
            12,
            23,
            13,
        )

    if stage == "success":
        launch()
        assert_that(root._child_created).is_true()
        assert_that(root._handle).is_equal_to(101)
        assert_that(calls).is_equal_to(
            ["create suspended", "close child pipes", "assign", "resume", "close 102"]
        )
    else:
        with pytest.raises(OSError, match=stage + " rejected"):
            launch()
        assert_that(calls).does_not_contain(
            "resume" if stage == "assign" else "target code"
        )
        if stage != "create":
            assert_that(calls[-4:]).is_equal_to(
                ["terminate root", "wait root", "close 101", "close 102"]
            )
        assert_that(getattr(root, "_child_created", False)).is_false()


@pytest.mark.parametrize(
    "stage", ["success", "terminate", "query", "reap", "active", "close"]
)
def test_windows_job_cleanup_independent_of_root(
    collector: dict[str, ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    """A reaped root never prevents job termination, query, bounded wait or close."""
    tree = collector["process_tree"]
    monkeypatch.setattr(tree, "os", SimpleNamespace(name="nt"))
    calls: list[str] = []

    def operation(name: str) -> None:
        """Model precise native operation failures without touching any PID."""
        calls.append(name)
        if stage == name:
            raise OSError(name + " rejected")

    def active() -> int:
        """Model an empty job or failed/nonempty membership observation."""
        operation("query")
        return 1 if stage == "active" else 0

    root = SimpleNamespace(
        pid=103,
        returncode=0,
        job=SimpleNamespace(
            terminate=lambda: operation("terminate"),
            active=active,
            close=lambda: operation("close"),
        ),
        wait=lambda **kwargs: operation("reap"),
    )
    result = tree.stop_process_tree(root, grace=0, forced=0)
    assert_that(calls[0]).is_equal_to("terminate")
    assert_that(calls[-1]).is_equal_to("close")
    assert_that(result["status"]).is_equal_to(
        "pass" if stage == "success" else "unverified"
    )
    count = len(calls)
    assert_that(tree.stop_process_tree(root)).is_equal_to(result)
    assert_that(calls).is_length(count)  # No repeat action against an exited PID.


@pytest.mark.parametrize("stage", ["setup", "launch", "success"])
def test_windows_job_factory_fail_closed(
    collector: dict[str, ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    """Job configuration failure prevents launch; launch failure closes ownership."""
    tree = collector["process_tree"]
    monkeypatch.setattr(tree, "os", SimpleNamespace(name="nt"))
    calls: list[str] = []
    job = SimpleNamespace(close=lambda: calls.append("close job"))

    def setup() -> SimpleNamespace:
        """Create ownership or reject setup before launch."""
        calls.append("setup")
        if stage == "setup":
            raise OSError("setup rejected")
        return job

    def launch(**kwargs: Any) -> SimpleNamespace:
        """Check the configured job is supplied to the suspended launch adapter."""
        calls.append("launch")
        assert_that(kwargs["job"]).is_same_as(job)
        if stage == "launch":
            raise OSError("launch rejected")
        return SimpleNamespace(job=job)

    monkeypatch.setattr(tree, "WindowsJob", setup)
    monkeypatch.setattr(tree, "JobPopen", launch)
    if stage == "success":
        root = tree.launch_process(args=["owned.exe"])
        tree.close_process(root)
        assert_that(calls).is_equal_to(["setup", "launch", "close job"])
    else:
        with pytest.raises(OSError, match=stage + " rejected"):
            tree.launch_process(args=["owned.exe"])
        assert_that(calls).is_equal_to(
            ["setup"] if stage == "setup" else ["setup", "launch", "close job"]
        )


@pytest.mark.parametrize(
    "stage",
    ["success", "create", "limits", "assign", "resume", "query", "terminate", "close"],
)
def test_windows_native_job_api_lifecycle(
    collector: dict[str, ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    """Real ctypes adapter checks every API failure and closes configured handles."""
    module = collector["windows_job"]
    calls: list[str] = []
    names = {
        "CreateJobObjectW": "create",
        "SetInformationJobObject": "limits",
        "AssignProcessToJobObject": "assign",
        "ResumeThread": "resume",
        "QueryInformationJobObject": "query",
        "TerminateJobObject": "terminate",
        "CloseHandle": "close",
    }

    def function(name: str) -> Any:
        """Build a mock Win32 function with real ctypes argument binding slots."""

        def invoke(*args: Any) -> int:
            """Validate the job's scope and return the selected native outcome."""
            operation = names[name]
            calls.append(operation)
            if name == "CreateJobObjectW":
                assert_that(args).is_equal_to((None, None))
            elif name == "SetInformationJobObject":
                assert_that(args[2]._obj.BasicLimitInformation.LimitFlags).is_equal_to(
                    0x2000
                )
            elif name == "QueryInformationJobObject":
                args[2]._obj.ActiveProcesses = 0
            if stage == operation:
                return 0xFFFFFFFF if operation == "resume" else 0
            return 99 if operation == "create" else 1

        return invoke

    api = SimpleNamespace(**{name: function(name) for name in names})
    monkeypatch.setattr(
        module.ctypes, "WinDLL", lambda *args, **kwargs: api, raising=False
    )
    monkeypatch.setattr(
        module.ctypes,
        "WinError",
        lambda error: OSError("native failure"),
        raising=False,
    )
    monkeypatch.setattr(module.ctypes, "get_last_error", lambda: 5, raising=False)

    def exercise() -> None:
        """Exercise setup and a complete launch/cleanup API sequence."""
        job = module.WindowsJob()
        try:
            job.assign(101)
            job.resume(102)
            assert_that(job.active()).is_zero()
            job.terminate()
        finally:
            job.close()
        job.close()  # Successful close is idempotent.

    if stage == "success":
        exercise()
        assert_that(calls).is_equal_to(
            ["create", "limits", "assign", "resume", "query", "terminate", "close"]
        )
    else:
        with pytest.raises(OSError):
            exercise()
        assert_that(calls[-1]).is_equal_to("create" if stage == "create" else "close")


def test_windows_job_abi_sizes(collector: dict[str, ModuleType]) -> None:
    """Hosted Windows verifies the native 64-bit structure layouts used by Win32."""
    if sys.platform == "win32":
        module = collector["windows_job"]
        assert_that(module.ctypes.sizeof(module.BasicLimits)).is_equal_to(64)
        assert_that(module.ctypes.sizeof(module.ExtendedLimits)).is_equal_to(144)
        assert_that(module.ctypes.sizeof(module.Accounting)).is_equal_to(48)


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
    assert_that(observed["ts"]["probe_denial_proven"]).is_true()
    assert_that(observed["ts"]["installer_denial_proven"]).is_true()


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
    monkeypatch.setenv("SPIKE_SOURCE_SHA", "head")
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


@pytest.mark.parametrize("force_fails", [False, True])
def test_posix_tree_shutdown_records_force_and_reap(
    collector: dict[str, ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    force_fails: bool,
) -> None:
    """A parent wait alone cannot certify live descendants, including reap errors."""
    tree = collector["process_tree"]
    monkeypatch.setattr(tree, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(tree, "signal", SimpleNamespace(SIGTERM=15, SIGKILL=9))
    signals: list[int] = []
    state = {"present": True, "waits": 0}

    def killpg(pid: int, sig: int) -> None:
        """Model the owned group surviving TERM and optionally surviving KILL.

        Args:
            pid: Explicit owned process group.
            sig: Requested signal, zero for observation.

        Raises:
            ProcessLookupError: Once the group disappears.
        """
        assert_that(pid).is_equal_to(31415)
        if sig:
            signals.append(sig)
            if sig == tree.signal.SIGKILL and not force_fails:
                state["present"] = False
        if not state["present"]:
            raise ProcessLookupError

    def wait(*, timeout: float) -> None:
        """Model bounded parent reap, independent of group survival.

        Args:
            timeout: Bounded wait.

        Raises:
            TimeoutExpired: During the failed forced-reap case.
        """
        state["waits"] += 1
        if force_fails:
            raise tree.subprocess.TimeoutExpired("fake", timeout)

    monkeypatch.setattr(tree.os, "killpg", killpg, raising=False)
    result = tree.stop_process_tree(
        SimpleNamespace(pid=31415, returncode=None if force_fails else 0, wait=wait),
        grace=0,
        forced=0,
    )
    assert_that(signals).is_equal_to([tree.signal.SIGTERM, tree.signal.SIGKILL])
    assert_that(result["status"]).is_equal_to("unverified" if force_fails else "pass")
    assert_that(result["parent_reaped"]).is_equal_to(not force_fails)
    assert_that(state["waits"]).is_equal_to(2)


def test_local_server_tree_shutdown_reaps_child(
    collector: dict[str, ModuleType],
    tmp_path: Path,
) -> None:
    """A harmless local server stand-in launches a child and shuts down as a tree."""
    import subprocess  # nosec B404 - fixed local Python process-tree probe
    import time

    tree = collector["process_tree"]
    code = (
        "import subprocess,sys,signal,time,pathlib\n"
        "child=subprocess.Popen([sys.executable,'-I','-c',"
        "'import time; time.sleep(30)'])\n"
        "def stop(*_):\n"
        " child.wait(timeout=2)\n"
        " sys.exit(0)\n"
        "signal.signal(signal.SIGTERM,stop)\n"
        "ready=pathlib.Path(sys.argv[1])\n"
        "ready.with_suffix('.tmp').write_text(str(child.pid))\n"
        "ready.with_suffix('.tmp').replace(ready)\n"
        "time.sleep(30)\n"
    )
    with tree.launch_process(
        args=[sys.executable, "-I", "-c", code, str(tmp_path / "ready")],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as process:
        stopped = False
        try:
            ready = tmp_path / "ready"
            deadline = time.monotonic() + 5
            while (
                not ready.is_file()
                and process.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            if not ready.is_file():
                pytest.fail("child readiness not observed within five seconds")
            child = int(ready.read_text(encoding="utf-8"))
            result = tree.stop_process_tree(process)
            stopped = True
            assert_that(result["parent_reaped"]).is_true()
            assert_that(result["status"]).described_as(str(result)).is_equal_to("pass")
            if sys.platform != "win32":
                import os

                with pytest.raises(ProcessLookupError):
                    os.kill(child, 0)
        finally:
            if not stopped:
                tree.stop_process_tree(process, grace=0, forced=1)


def test_missing_reused_tarballs_do_not_start_installers(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed control's absent archives leave restricted installation unverified."""
    offline = collector["offline"]
    monkeypatch.setattr(offline, "identity", lambda: {"effective_uid": 123})
    monkeypatch.setattr(offline.shutil, "which", lambda _: "/fake/bun")
    monkeypatch.setattr(
        offline,
        "install_client",
        lambda **_: pytest.fail("missing tarballs reached installer"),
    )
    result = offline.worker(
        build=tmp_path, work=tmp_path / "restricted", packages_from=tmp_path / "control"
    )
    for item in result.values():
        assert_that(item["status"]).is_equal_to("unverified")
        assert_that(item["missing_archives"]).is_length(6)
        assert_that(item["clients"]).is_empty()


@pytest.mark.parametrize(
    "full_parent",
    ["C:/Users/runneradmin/Temp", "C:/Users/RUNNER~1/Temp", "//server/share/Temp"],
)
def test_firewall_resolves_existing_ancestor_before_future_suffix(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    full_parent: str,
) -> None:
    """Resolve an existing ancestor; reject remaining short aliases and UNC paths."""
    from pathlib import PureWindowsPath

    monkeypatch.setattr(
        Path, "resolve", lambda path, *, strict: PureWindowsPath(full_parent)
    )
    path = (
        tmp_path
        / "installs/client/node_modules/@spike/ts-windows-x64/payload/spike.exe"
    )
    if "~" in full_parent or full_parent.startswith("//"):
        with pytest.raises(ValueError, match="unsafe firewall program"):
            collector["offline"].firewall_program(path)
    else:
        result = collector["offline"].firewall_program(path)
        assert_that(result["program"]).is_equal_to(
            str(PureWindowsPath(full_parent) / path.relative_to(tmp_path))
        )
        assert_that(result["exists"]).is_false()
        assert_that(result["future_suffix"][0]).is_equal_to("installs")


@pytest.mark.parametrize("invalid", ["mismatch", "dirty", "missing-expected"])
def test_hosted_source_identity_exports_invalid_evidence_without_scenarios(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: str,
) -> None:
    """A wrong checkout fails closed before starting any measurement."""
    measure = collector["measure"]
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SPIKE_SOURCE_SHA", "expected-head")
    if invalid == "missing-expected":
        monkeypatch.delenv("SPIKE_SOURCE_SHA")
    monkeypatch.setattr(
        measure,
        "command",
        lambda **kwargs: {
            "exit": 0,
            "stdout": (
                (
                    " M research/install-plane-spike/py/prototype.py\n"
                    if invalid == "dirty"
                    else ""
                )
                if "status" in kwargs["argv"]
                else ("wrong-head" if invalid == "mismatch" else "expected-head")
            ),
        },
    )
    monkeypatch.setattr(
        measure, "measure_offline", lambda **_: pytest.fail("invalid checkout measured")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "measure.py",
            "--build",
            str(tmp_path / "build"),
            "--results",
            str(tmp_path / "results"),
        ],
    )
    with pytest.raises(ValueError, match="source head"):
        measure.main()
    for path in (tmp_path / "results").glob("*.json"):
        result = json.loads(path.read_bytes())
        assert_that(result["status"]).is_equal_to("invalid")
        assert_that(result).does_not_contain_key("offline")


@pytest.mark.parametrize("hosted", [False, True])
def test_collection_scope_and_unbound_downloads_are_explicit(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hosted: bool,
) -> None:
    """Record hosted attempts and distinguish local dirty observations."""
    measure = collector["measure"]
    monkeypatch.setenv("GITHUB_ACTIONS", "true" if hosted else "false")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    if hosted:
        monkeypatch.setenv("SPIKE_SOURCE_SHA", "head")
    else:
        monkeypatch.delenv("SPIKE_SOURCE_SHA", raising=False)
    monkeypatch.setattr(
        measure,
        "command",
        lambda **kwargs: {
            "exit": 0,
            "stdout": (
                ("" if hosted else " M local.py\n")
                if "status" in kwargs["argv"]
                else "head"
            ),
        },
    )
    monkeypatch.setattr(
        measure,
        "measure_offline",
        lambda **_: {v: {"status": "unverified"} for v in ("ts", "py")},
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
    measure.main()
    saved = [
        json.loads(path.read_bytes()) for path in (tmp_path / "results").glob("*.json")
    ]
    assert_that(saved).is_length(2)
    for item in saved:
        assert_that(item["collection_scope"]).is_equal_to(
            "hosted" if hosted else "local observation"
        )
        assert_that(item["workflow_run_attempt"]).is_equal_to("2")
        assert_that(item["payload_source_identity"]["status"]).is_equal_to("unverified")
        assert_that(item["payload_source_identity"]["reason"]).contains("not bound")


@pytest.mark.parametrize("unexpected_write", ["none", "file", "symlink"])
@pytest.mark.parametrize(
    "cache_mutation", ["unchanged", "deleted", "overwritten", "directory", "symlink"]
)
def test_payload_home_write_affects_status(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unexpected_write: str,
    cache_mutation: str,
) -> None:
    """Correct output cannot hide an unexpected runtime cache write under HOME."""
    common = collector["common"]
    monkeypatch.setattr(common, "isolated_env", lambda _: {"PATH": ""})
    expected = json.loads((SPIKE / "fixtures/expected-output.json").read_bytes())
    home = tmp_path / "home"

    def command(**kwargs: Any) -> dict[str, Any]:
        """Model golden output and optionally an unrequested HOME cache file.

        Args:
            kwargs: Unused command inputs.

        Returns:
            Successful payload stdout with exact on-disk output.
        """
        for name, content in expected.items():
            path = home / ".spike-target" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        if unexpected_write == "file":
            (home / "runtime-cache").write_bytes(b"unexpected")
        elif unexpected_write == "symlink":
            outside = tmp_path / "outside"
            outside.mkdir()
            (outside / "private-file").write_bytes(b"never read")
            (home / "runtime-cache").symlink_to(outside, target_is_directory=True)
        cache = home / ".cache"
        if cache_mutation == "overwritten":
            cache.write_bytes(b"overwritten")
        elif cache_mutation != "unchanged":
            cache.unlink()
            if cache_mutation == "directory":
                cache.mkdir()
            elif cache_mutation == "symlink":
                unrelated = tmp_path / "unrelated"
                unrelated.mkdir()
                (unrelated / "secret").write_bytes(b"never traverse")
                cache.symlink_to(unrelated, target_is_directory=True)
        return {"exit": 0, "seconds": 0.01, "stdout": json.dumps(expected)}

    monkeypatch.setattr(common, "command", command)
    result = common.run_payload(root=SPIKE, variant="ts", home=home, records=[])
    assert_that(result["status"]).is_equal_to(
        "pass"
        if unexpected_write == "none" and cache_mutation == "unchanged"
        else "fail"
    )
    assert_that(result["cache_directory_blocked"]).is_equal_to(
        cache_mutation == "unchanged"
    )
    assert_that(result["other_HOME_files"]).is_equal_to(
        ["runtime-cache"] if unexpected_write != "none" else []
    )


@pytest.mark.parametrize("tool", ["node", "nodejs", "bun", "bunx"])
@pytest.mark.parametrize("suffix", ["", ".exe", ".cmd", ".custom"])
def test_isolation_filters_alias_only_directories(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    suffix: str,
) -> None:
    """Alias-only PATH directories and every explicit PATHEXT suffix are removed."""
    common = collector["common"]
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / (tool + suffix)).write_bytes(b"not run")
    monkeypatch.setenv("PATH", str(tools))
    monkeypatch.setenv("PATHEXT", ".EXE;.CMD;.CUSTOM")
    assert_that(common.isolated_env(tmp_path / "home")["PATH"]).is_empty()


@pytest.mark.parametrize("tool", ["node", "nodejs", "bun", "bunx"])
def test_no_node_gate_rejects_resolvable_tool_before_execution(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
) -> None:
    """No-Node evidence cannot pass if environment filtering leaves an executable."""
    common = collector["common"]
    node = tmp_path / (f"{tool}.exe" if sys.platform == "win32" else tool)
    node.write_bytes(b"not executed")
    node.chmod(0o755)
    monkeypatch.setattr(
        common,
        "isolated_env",
        lambda _: {"PATH": str(tmp_path), "PATHEXT": ".EXE;.CMD"},
    )
    monkeypatch.setattr(
        common, "command", lambda **_: pytest.fail("resolvable tool reached payload")
    )
    result = common.run_payload(
        root=tmp_path, variant="ts", home=tmp_path / "home", records=[]
    )
    assert_that(result["status"]).is_equal_to("fail")
    assert_that(result["reason"]).contains("still resolvable")


@pytest.mark.parametrize(
    "scan_exit,output,expected",
    [
        (0, "Scan found no threats.", "measured"),
        (2, "Threat detected", "fail"),
        (5, "engine error", "unverified"),
    ],
)
def test_windows_quarantine_summary_reflects_scan(
    collector: dict[str, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scan_exit: int,
    output: str,
    expected: str,
) -> None:
    """Direct execution success cannot hide a Defender threat or unknown scan."""
    quarantine = collector["quarantine"]
    monkeypatch.setattr(quarantine, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr(quarantine.platform, "system", lambda: "Windows")
    monkeypatch.setattr(quarantine.shutil, "which", lambda _: "powershell.exe")
    monkeypatch.setattr(Path, "is_file", lambda p: p.name == "MpCmdRun.exe")
    monkeypatch.setattr(quarantine, "run_payload", lambda **_: {"status": "pass"})

    def command(**kwargs: Any) -> dict[str, Any]:
        """Supply engine, marking and scan output without a Windows invocation.

        Args:
            kwargs: Measured native command arguments.

        Returns:
            Explicit engine and selected scan outcome.
        """
        argv = kwargs["argv"]
        if "-Scan" in argv:
            return {"exit": scan_exit, "stdout": output, "stderr": ""}
        return {
            "exit": 0,
            "stdout": json.dumps({"AMServiceEnabled": True, "AntivirusEnabled": True}),
        }

    monkeypatch.setattr(quarantine, "command", command)
    result = quarantine.measure_quarantine(
        root=tmp_path, variant="ts", home=tmp_path / "home"
    )
    assert_that(result["status"]).is_equal_to(expected)
    assert_that(result["execution_status"]).is_equal_to("pass")
    assert_that(result["security_enforcement"]).starts_with("unverified")
