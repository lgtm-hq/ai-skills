"""Root fixture discovery must support the engine-free native spike environment."""

import json
import os
import subprocess  # nosec B404 - bounded local pytest discovery, no shell
import sys
from pathlib import Path

import pytest
from assertpy import assert_that

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mixed", [False, True], ids=["root-parity", "mixed-spike"])
def test_plugin_discovery_without_engine_or_bun(mixed: bool) -> None:
    """Collect the real parity tests while engine imports fail and Bun is absent."""
    paths = [str(ROOT / "tests/test_install_plane_parity.py")]
    if mixed:
        paths.insert(0, str(ROOT / "research/install-plane-spike/tests"))
    program = """
import importlib.abc
import json
import sys
sys.path[:0] = json.loads(sys.argv[1])
import pytest

class NoEngine(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'ai_skills_engine' or fullname.startswith('ai_skills_engine.'):
            raise ModuleNotFoundError('Engine unavailable during plugin discovery')

sys.meta_path.insert(0, NoEngine())
result = pytest.main(['--collect-only', '-q', '-o', 'addopts=', *sys.argv[2:]])
if any(name.startswith('ai_skills_engine') for name in sys.modules):
    raise RuntimeError('Discovery loaded the engine')
sys.exit(result)
"""
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}
    }
    env["PATH"] = ""
    # Prepared Python environments may provide dependencies from multiple sites.
    # Retain those sites, while -I removes source paths and NoEngine bars imports.
    sites = [entry for entry in sys.path if Path(entry).name == "site-packages"]
    result = subprocess.run(  # nosec B603 - local interpreter and literal probe
        args=[sys.executable, "-I", "-c", program, json.dumps(sites), *paths],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert_that(result.returncode).described_as(result.stdout + result.stderr).is_zero()
    assert_that(result.stdout).contains(
        "test_spike_golden", "test_spike_runtime_parity", "tests collected"
    )
