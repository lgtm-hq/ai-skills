"""Check protected-inventory coverage using only a disposable home."""

import json
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
def snapshot_process(tmp_path: Path) -> Callable[[], dict[str, Any]]:
    """Run the copied collector with HOME confined to a disposable directory."""
    source = Path(__file__).resolve().parent / "fixtures/host-probe/config_snapshot.py"
    script = shutil.copy2(src=source, dst=tmp_path / "config_snapshot.py")
    home = tmp_path / "home"
    home.mkdir()
    destination = tmp_path / "snapshot.json"

    def run() -> dict[str, Any]:
        """Return synthetic inventory records without touching the real home."""
        result = (
            subprocess.run(  # nosec B603 - current Python, copied fixture, no shell
                [sys.executable, "-I", str(script), str(destination)],
                capture_output=True,
                text=True,
                cwd=tmp_path,
                env={"HOME": str(home), "USERPROFILE": str(home)},
                timeout=5,
                check=False,
            )
        )
        assert_that(result.returncode).is_zero()
        assert_that(result.stderr).is_empty()
        records: dict[str, Any] = json.loads(destination.read_text(encoding="utf-8"))
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
