"""Check protected-inventory coverage using only a disposable home."""

import json
import runpy
import shutil
import subprocess  # nosec B404 - copied local fixture only, no shell or host CLI
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that

PAYLOAD_NAMES = (
    "sessions",
    "logs",
    "debug",
    "telemetry",
    "projects",
    "backups",
    "shell_snapshots",
    "tmp",
    "session-env",
    "todos",
    "paste-cache",
    "file-history",
    "plans",
)


@pytest.fixture
def snapshot_command(
    tmp_path: Path,
) -> Callable[[Path], subprocess.CompletedProcess[str]]:
    """Run the copied collector with HOME confined to a disposable directory."""
    source = Path(__file__).resolve().parent / "fixtures/host-probe/config_snapshot.py"
    script = shutil.copy2(src=source, dst=tmp_path / "config_snapshot.py")
    home = tmp_path / "home"
    home.mkdir()
    destination = tmp_path / "snapshot.json"

    def run(home: Path) -> subprocess.CompletedProcess[str]:
        """Collect a synthetic HOME, preserving failures for regression checks."""
        return subprocess.run(  # nosec B603 - current Python, copied fixture, no shell
            [sys.executable, "-I", str(script), str(destination)],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={"HOME": str(home), "USERPROFILE": str(home)},
            timeout=5,
            check=False,
        )

    return run


@pytest.fixture
def snapshot_process(
    snapshot_command: Callable[[Path], subprocess.CompletedProcess[str]],
    tmp_path: Path,
) -> Callable[[], dict[str, Any]]:
    """Return successful records from the disposable HOME only."""

    def run() -> dict[str, Any]:
        """Check the collector's success summary against its private artifact."""
        result = snapshot_command(tmp_path / "home")
        assert_that(result.returncode).is_zero()
        assert_that(result.stderr).is_empty()
        records: dict[str, Any] = json.loads(
            (tmp_path / "snapshot.json").read_text(encoding="utf-8"),
        )
        assert_that(json.loads(result.stdout)["files"]).is_equal_to(len(records))
        return records

    return run


@pytest.mark.parametrize("host", [".agents", ".claude", ".codex", ".cursor"])
@pytest.mark.parametrize("layout", ["skills", "plugins/cache/example/1.0.0/skills"])
def test_named_payload_changes_and_deletions_are_inventoried(
    snapshot_process: Callable[[], dict[str, Any]],
    tmp_path: Path,
    host: str,
    layout: str,
) -> None:
    """Runtime-like names inside skill and plugin payloads stay protected."""
    payloads = []
    for name in PAYLOAD_NAMES:
        payload = tmp_path / "home" / host / layout / name / "SKILL.md"
        payload.parent.mkdir(parents=True)
        payload.write_text("Original offline skill\n", encoding="utf-8")
        payloads.append(payload)
    before = snapshot_process()
    keys = [f"~/{host}/{layout}/{name}/SKILL.md" for name in PAYLOAD_NAMES]
    assert_that(before).contains_key(*keys)

    for payload in payloads:
        payload.write_text("Changed offline skill\n", encoding="utf-8")
    changed = snapshot_process()
    assert_that(changed).is_not_equal_to(before)
    for key in keys:
        assert_that(changed[key]["sha256"]).is_not_equal_to(before[key]["sha256"])

    for payload in payloads:
        payload.unlink()
    deleted = snapshot_process()
    assert_that(deleted).is_not_equal_to(changed).is_not_equal_to(before)
    for key in keys:
        assert_that(deleted).does_not_contain_key(key)


def test_runtime_roots_are_host_specific(
    snapshot_process: Callable[[], dict[str, Any]],
    tmp_path: Path,
) -> None:
    """Only known runtime roots are excluded; names elsewhere remain covered."""
    runtime_roots = {
        ".claude": (
            "projects",
            "debug",
            "telemetry",
            "backups",
            "tmp",
            "session-env",
            "todos",
            "paste-cache",
            "file-history",
            "plans",
        ),
        ".codex": ("sessions", "logs", "log", "shell_snapshots", "tmp"),
        ".cursor": ("logs", "projects"),
    }
    for host, roots in runtime_roots.items():
        for root in roots:
            payload = tmp_path / "home" / host / root / "nested/runtime.json"
            payload.parent.mkdir(parents=True)
            payload.write_text('{"synthetic": true}\n', encoding="utf-8")
    protected = (
        ".agents/plans/SKILL.md",
        ".agents/sessions/SKILL.md",
        ".codex/plans/SKILL.md",
        ".cursor/sessions/SKILL.md",
        ".claude/shell_snapshots/SKILL.md",
        ".claude/plans-extra/SKILL.md",
        ".codex/sessions.json",
    )
    for relative in protected:
        payload = tmp_path / "home" / relative
        payload.parent.mkdir(parents=True, exist_ok=True)
        payload.write_text("Offline configuration\n", encoding="utf-8")
    before = snapshot_process()
    assert_that(set(before)).is_equal_to({f"~/{relative}" for relative in protected})
    for host, roots in runtime_roots.items():
        for root in roots:
            payload = tmp_path / "home" / host / root / "nested/runtime.json"
            payload.write_text('{"synthetic": false}\n', encoding="utf-8")
    assert_that(snapshot_process()).is_equal_to(before)


@pytest.mark.parametrize("host", [".agents", ".claude", ".codex", ".cursor"])
@pytest.mark.parametrize(
    "case",
    ["skill", "plugin", "ancestor", "root", "dangling", "dangling-root", "cycle"],
)
def test_linked_payload_never_produces_unchanged_success(
    snapshot_command: Callable[[Path], subprocess.CompletedProcess[str]],
    tmp_path: Path,
    host: str,
    case: str,
) -> None:
    """Linked skills/plugins, ancestors, roots and cycles fail before publication."""
    home = tmp_path / "home"
    target = tmp_path / "shared"
    target.mkdir()
    skill = target / "SKILL.md"
    skill.write_text("Original offline skill\n", encoding="utf-8")
    locations = {
        "skill": f"{host}/skills/example",
        "plugin": f"{host}/plugins/cache/example/1.0.0",
        "ancestor": f"{host}/skills",
        "root": host,
        "dangling": f"{host}/skills/example",
        "dangling-root": host,
        "cycle": f"{host}/skills/example",
    }
    link = home / locations[case]
    link.parent.mkdir(parents=True, exist_ok=True)
    if case.startswith("dangling"):
        target = tmp_path / "missing"
    elif case == "cycle":
        target = link.parent
    link.symlink_to(target, target_is_directory=True)

    for content in ("Original offline skill\n", "Changed offline skill\n"):
        skill.write_text(content, encoding="utf-8")
        result = snapshot_command(home)
        assert_that(result.returncode).is_not_zero()
        assert_that(result.stdout).is_empty()
        assert_that(result.stderr).contains("Snapshot incomplete")
        assert_that((tmp_path / "snapshot.json").exists()).is_false()


@pytest.mark.parametrize("case", ["home", "home-ancestor", "config-file", "self-cycle"])
def test_other_links_fail_closed(
    snapshot_command: Callable[[Path], subprocess.CompletedProcess[str]],
    tmp_path: Path,
    case: str,
) -> None:
    """HOME aliases, standalone config links and self-cycles are unsupported too."""
    home = tmp_path / "home"
    if case in {"home", "home-ancestor"}:
        alias = tmp_path / "alias"
        alias.symlink_to(home if case == "home" else tmp_path, target_is_directory=True)
        home = alias if case == "home" else alias / "home"
    else:
        link = home / (".claude.json" if case == "config-file" else ".agents")
        link.symlink_to(link if case == "self-cycle" else tmp_path / "missing")
    result = snapshot_command(home)
    assert_that(result.returncode).is_not_zero()
    assert_that(result.stdout).is_empty()
    assert_that(result.stderr).contains("Snapshot incomplete")
    assert_that((tmp_path / "snapshot.json").exists()).is_false()


@pytest.mark.parametrize("operation", ["iterdir", "lstat", "read_bytes"])
def test_unreadable_protected_path_is_not_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """Injected permission failures propagate even when tests run as root."""
    source = Path(__file__).resolve().parent / "fixtures/host-probe/config_snapshot.py"
    collect = runpy.run_path(str(source))["snapshot"]
    home = tmp_path / "home"
    directory = home / ".agents/skills/example"
    directory.mkdir(parents=True)
    payload = directory / "SKILL.md"
    payload.write_text("Offline skill\n", encoding="utf-8")
    original = getattr(Path, operation)
    failed = directory if operation == "iterdir" else payload

    def deny(path: Path) -> Any:
        """Fail only the selected synthetic node, never access a real HOME."""
        if path == failed:
            raise PermissionError("Injected protected-path denial")
        return original(path)

    monkeypatch.setattr(Path, operation, deny)
    with pytest.raises(PermissionError, match="Injected protected-path denial"):
        collect(home)
