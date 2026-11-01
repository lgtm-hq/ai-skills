"""Exercise both throwaway runtimes against shared data, without network access."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess  # nosec B404 - fixed local prototypes, no shell or network
import sys
from pathlib import Path
from types import ModuleType

import pytest
from assertpy import assert_that

SPIKE = Path(__file__).resolve().parents[1] / "research" / "install-plane-spike"


@pytest.fixture
def prototype() -> ModuleType:
    """Import this checkout's prototype explicitly, independent of PYTHONPATH.

    Returns:
        Local Python installer module.
    """
    path = SPIKE / "py" / "prototype.py"
    spec = importlib.util.spec_from_file_location("spike_prototype", path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load local prototype")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert_that(module.__file__).is_equal_to(str(path))
    return module


@pytest.fixture
def spike_fixture(tmp_path: Path) -> Path:
    """Copy the shared golden fixture for isolated mutations.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        Writable fixture copy.
    """
    return Path(shutil.copytree(src=SPIKE / "fixtures", dst=tmp_path / "fixture"))


def test_spike_golden(
    prototype: ModuleType, spike_fixture: Path, tmp_path: Path
) -> None:
    """Python materializes only the expected retained capability."""
    expected = json.loads((spike_fixture / "expected-output.json").read_text())
    output = prototype.install(
        fixture=spike_fixture, home=tmp_path, exclude="fixture:drop"
    )
    assert_that(output).is_equal_to(expected)
    target = tmp_path / ".spike-target"
    actual = {
        p.relative_to(target).as_posix(): p.read_text()
        for p in target.rglob("*")
        if p.is_file()
    }
    assert_that(actual).is_equal_to(expected)
    index = json.loads((spike_fixture / "index.json").read_text())
    digest = next(c for c in index["capabilities"] if c["id"] == "fixture:keep")[
        "files"
    ]["keep/SKILL.md"]
    installed = (target / "keep/SKILL.md").read_bytes()
    assert_that(installed.startswith(b"\xef\xbb\xbf")).is_true()
    assert_that(hashlib.sha256(installed).hexdigest()).is_equal_to(digest)


@pytest.mark.parametrize(
    "mutation",
    [
        "archive",
        "file",
        "closure",
        "missing-closure",
        "unknown-closure",
        "path",
        "duplicate",
        "case-file",
        "case-directory",
        "file-directory",
        "reserved-file",
        "reserved-directory",
    ],
)
def test_spike_rejects_before_writing(
    prototype: ModuleType,
    spike_fixture: Path,
    tmp_path: Path,
    mutation: str,
) -> None:
    """Digest, closure and inventory failures leave no target tree."""
    path = spike_fixture / "index.json"
    index = json.loads(path.read_text())
    keep = next(cap for cap in index["capabilities"] if cap["id"] == "fixture:keep")
    if mutation == "archive":
        index["sha256"] = "0" * 64
    elif mutation == "file":
        keep["files"]["keep/SKILL.md"] = "0" * 64
    elif mutation == "closure":
        keep["closure"] = ["fixture:drop"]
    elif mutation == "missing-closure":
        del keep["closure"]
    elif mutation == "unknown-closure":
        keep["closure"] = ["fixture:missing"]
    elif mutation == "path":
        keep["files"] = {"../escape": "0" * 64}
    elif mutation == "duplicate":
        index["capabilities"].append(keep)
    elif mutation == "case-file":
        index["capabilities"][0]["files"]["keep/skill.MD"] = "0" * 64
    elif mutation == "case-directory":
        keep["files"]["KEEP/other.md"] = "0" * 64
    elif mutation == "file-directory":
        keep["files"]["keep/SKILL.md/child"] = "0" * 64
    elif mutation == "reserved-file":
        keep["files"]["keep/nUl.txt"] = "0" * 64
    elif mutation == "reserved-directory":
        keep["files"]["COM1/child.md"] = "0" * 64
    path.write_text(json.dumps(index))
    with pytest.raises(ValueError):
        prototype.install(fixture=spike_fixture, home=tmp_path, exclude="fixture:drop")
    assert_that((tmp_path / ".spike-target").exists()).is_false()


def test_spike_runtime_parity(spike_fixture: Path, tmp_path: Path) -> None:
    """Both CLIs emit and write the same golden fixture, with isolated HOME."""
    bun = shutil.which("bun")
    if bun is None:
        if os.environ.get("SPIKE_REQUIRE_BUN") == "1":
            pytest.fail("Bun required for spike CI parity")
        pytest.skip("Bun not installed; dispatch workflow requires the parity check")
    expected = json.loads((spike_fixture / "expected-output.json").read_text())
    for variant, command in {
        "py": [sys.executable, "-I", "-B", str(SPIKE / "py/prototype.py")],
        "ts": [bun, "run", str(SPIKE / "ts/prototype.ts")],
    }.items():
        home = tmp_path / variant
        home.mkdir()
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        env["HOME"] = str(home)
        result = subprocess.run(  # nosec B603 - trusted local prototypes, fixed argv
            args=[*command, str(spike_fixture), "fixture:drop"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=30,
        )
        assert_that(result.returncode).described_as(result.stderr).is_zero()
        assert_that(json.loads(result.stdout)).is_equal_to(expected)
        target = home / ".spike-target"
        actual = {
            p.relative_to(target).as_posix(): p.read_text()
            for p in target.rglob("*")
            if p.is_file()
        }
        assert_that(actual).is_equal_to(expected)
        assert_that((target / "keep/SKILL.md").read_bytes()).is_equal_to(
            expected["keep/SKILL.md"].encode("utf-8")
        )


@pytest.fixture
def measurement() -> ModuleType:
    """Import measurement helpers directly from this checkout.

    Returns:
        The spike's stdlib-only command and observation helpers.
    """
    spec = importlib.util.spec_from_file_location(
        "spike_measurement",
        SPIKE / "scripts/common.py",
    )
    if spec is None or spec.loader is None:
        raise ValueError("cannot load local measurement helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_spike_missing_command_is_unverified(
    measurement: ModuleType,
    tmp_path: Path,
) -> None:
    """A command that cannot launch must not be recorded as exit zero."""
    records: list[dict[str, object]] = []
    result = measurement.command(
        argv=[str(tmp_path / "absent-executable")],
        cwd=tmp_path,
        records=records,
    )
    assert_that(result["exit"]).is_none()
    assert_that(result["stderr"]).is_not_empty()
    assert_that(records).is_length(1)


def test_spike_measurement_rejects_hollow_success(
    measurement: ModuleType,
    spike_fixture: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exit-zero process printing golden JSON without writing files fails."""
    expected = json.loads((spike_fixture / "expected-output.json").read_text())
    root = tmp_path / "payload"
    root.mkdir()
    shutil.copytree(src=spike_fixture, dst=root / "fixtures")

    def fake_command(**kwargs: object) -> dict[str, object]:
        """Model a process lying about a successful install.

        Args:
            kwargs: Unused command arguments.

        Returns:
            Success-looking stdout with no filesystem effects.
        """
        return {"exit": 0, "stdout": json.dumps(expected), "seconds": 0.01}

    monkeypatch.setattr(measurement, "command", fake_command)
    observed = measurement.run_payload(
        root=root,
        variant="py",
        home=tmp_path / "home",
        records=[],
    )
    assert_that(observed["status"]).is_equal_to("fail")


def test_spike_fixture_drift_gate() -> None:
    """The checked-in data artifact exactly matches its deterministic generator."""
    result = subprocess.run(  # nosec B603 - local stdlib generator, no network
        args=[sys.executable, str(SPIKE / "scripts/fixture.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert_that(result.returncode).described_as(result.stdout + result.stderr).is_zero()
