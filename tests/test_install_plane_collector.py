"""Collector boundary regressions: no network, firewall changes or real servers."""

from __future__ import annotations

import importlib
import json
import secrets
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from assertpy import assert_that

SPIKE = Path(__file__).resolve().parents[1] / "research/install-plane-spike"


@pytest.fixture
def collector(monkeypatch: pytest.MonkeyPatch) -> dict[str, ModuleType]:
    """Import collector modules from this checkout with reversible search paths.

    Args:
        monkeypatch: Reversible import path updates.

    Returns:
        Local stdlib collector modules.
    """
    monkeypatch.syspath_prepend(str(SPIKE / "scripts"))
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
    return modules


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
            "text",
            "eol",
            "--",
            *[str(SPIKE / path) for path in paths],
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    for path in paths[:3]:
        assert_that(result.stdout).contains(f"{path}: text: unset")
    for path in paths[3:]:
        assert_that(result.stdout).contains(f"{path}: eol: lf")


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
            path.write_text(json.dumps({v: {"status": "pass"} for v in ("ts", "py")}))
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
        ("account", 201, {"token": 42}),
        ("account", 201, {"token": chr(32)}),
        ("account", 201, b"unreadable JSON"),
        ("account", 201, TimeoutError()),
        ("readiness", 503, {}),
        ("readiness", 200, TimeoutError()),
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
    monkeypatch.setattr(
        registry.subprocess,
        "Popen",
        lambda **_: SimpleNamespace(
            returncode=0,
            poll=lambda: None,
            terminate=lambda: None,
            wait=lambda **_: None,
        ),
    )
    result = registry.measure_registry(build=tmp_path / "build", work=tmp_path)
    assert_that(result["ts"]["status"]).is_equal_to("fail")
    assert_that(result["py"]["status"]).is_equal_to("fail")
    assert_that(result["server"]).is_not_empty()
    assert_that(json.dumps(result)).does_not_contain(password)
    assert_that((tmp_path / "registry-evidence.json").is_file()).is_true()


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
    path.write_text('{"status":"unverified"}\n')
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    collector["common"].export_evidence(path)
    assert_that(capsys.readouterr().out).contains(path.read_text())
    assert_that(summary.read_text()).contains(path.read_text())


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
        saved = json.loads(next(results.glob("*-ts.json")).read_text())
        assert_that(saved).contains_key("offline", "quarantine", "footprint")
        raise TimeoutError("test boundary")

    monkeypatch.setattr(measure, "measure_registry", broken_registry)
    monkeypatch.setattr(
        sys, "argv", ["measure.py", "--build", str(build), "--results", str(results)]
    )
    measure.main()
    saved = json.loads(next(results.glob("*-ts.json")).read_text())
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


def test_disabled_gatekeeper_cannot_prove_enforcement(
    collector: dict[str, ModuleType], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attribute and CLI success remain unverified when Gatekeeper is disabled."""
    quarantine = collector["quarantine"]
    monkeypatch.setattr(quarantine.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(quarantine.shutil, "which", lambda name: f"/fake/{name}")
    monkeypatch.setattr(quarantine, "run_payload", lambda **_: {"status": "pass"})
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
    assert_that(observed["status"]).is_equal_to("unverified")
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
