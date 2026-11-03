"""Offline regression fixtures scoped to manifest authoring and vendor pin tests."""

import shutil
import subprocess  # nosec B404 - bounded local lint process, no shell
from collections.abc import Callable
from pathlib import Path

import pytest
from assertpy import assert_that

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def author_skills(tmp_path: Path) -> None:
    """Supply the actual first-party payloads declared by publication fixtures."""
    shutil.copytree(src=SCRIPTS_DIR.parent / "skills", dst=tmp_path / "skills")


@pytest.fixture
def check_yaml() -> Callable[[Path], None]:
    """Check generated YAML with the same configuration used by Lintro.

    Returns:
        Assertion helper invoking the installed yamllint tool without acquisition.
    """

    def check(path: Path) -> None:
        """Lint one real author output using repository rules."""
        executable = shutil.which("yamllint")
        if executable is None:
            pytest.fail("yamllint is required to check generated registry layout")
        result = subprocess.run(  # nosec B603 - fixed local tool argv, no shell
            [executable, "-c", str(SCRIPTS_DIR.parent / ".yamllint"), str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert_that(result.returncode).described_as(
            result.stdout + result.stderr
        ).is_zero()

    return check
