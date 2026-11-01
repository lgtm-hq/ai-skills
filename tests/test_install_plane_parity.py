"""Keep the shared golden fixture and runtime parity in the main pytest suite."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess  # nosec B404 - fixed local prototypes, no shell or network
import sys
from pathlib import Path
from types import ModuleType

import pytest
import spike_helpers
from assertpy import assert_that
from spike_helpers import SPIKE

non_utf8_locale = spike_helpers.non_utf8_locale
prototype = spike_helpers.prototype
spike_fixture = spike_helpers.spike_fixture


def test_spike_golden(
    prototype: ModuleType, spike_fixture: Path, tmp_path: Path
) -> None:
    """Python materializes only the expected retained capability."""
    expected = json.loads(
        (spike_fixture / "expected-output.json").read_text(encoding="utf-8")
    )
    output = prototype.install(
        fixture=spike_fixture, home=tmp_path, exclude="fixture:drop"
    )
    assert_that(output).is_equal_to(expected)
    target = tmp_path / ".spike-target"
    actual = {
        p.relative_to(target).as_posix(): p.read_text(encoding="utf-8")
        for p in target.rglob("*")
        if p.is_file()
    }
    assert_that(actual).is_equal_to(expected)
    index = json.loads((spike_fixture / "index.json").read_text(encoding="utf-8"))
    digest = next(c for c in index["capabilities"] if c["id"] == "fixture:keep")[
        "files"
    ]["keep/SKILL.md"]
    installed = (target / "keep/SKILL.md").read_bytes()
    assert_that(installed.startswith(b"\xef\xbb\xbf")).is_true()
    assert_that(hashlib.sha256(installed).hexdigest()).is_equal_to(digest)


def test_spike_runtime_parity(spike_fixture: Path, tmp_path: Path) -> None:
    """Both CLIs emit and write the same golden fixture, with isolated HOME."""
    bun = shutil.which("bun")
    if bun is None:
        if os.environ.get("SPIKE_REQUIRE_BUN") == "1":
            pytest.fail("Bun required for spike CI parity")
        pytest.skip("Bun not installed; dispatch workflow requires the parity check")
    expected = json.loads(
        (spike_fixture / "expected-output.json").read_text(encoding="utf-8")
    )
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
            p.relative_to(target).as_posix(): p.read_text(encoding="utf-8")
            for p in target.rglob("*")
            if p.is_file()
        }
        assert_that(actual).is_equal_to(expected)
        assert_that((target / "keep/SKILL.md").read_bytes()).is_equal_to(
            expected["keep/SKILL.md"].encode("utf-8")
        )
