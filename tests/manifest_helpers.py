"""Offline regression fixtures scoped to manifest authoring and vendor pin tests."""

import json
import re
import shutil
import subprocess  # nosec B404 - bounded local lint process, no shell
from collections.abc import Callable
from pathlib import Path

import pytest
from assertpy import assert_that

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


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


@pytest.fixture
def vendor_pin_matches() -> Callable[[str], list[re.Match[str]]]:
    """Apply the production Renovate recursive manager with original source spans.

    Returns:
        Extractor for the actual ordered custom-manager patterns.
    """
    manager = next(
        item
        for item in json.loads((SCRIPTS_DIR.parent / "renovate.json").read_text())[
            "customManagers"
        ]
        if item.get("datasourceTemplate") == "git-refs"
    )

    def extract(text: str) -> list[re.Match[str]]:
        """Recurse within each previous match as Renovate's strategy specifies."""
        windows = [(0, len(text))]
        matches = []
        for pattern in manager["matchStrings"]:
            regex = re.compile(pattern.replace("(?<", "(?P<"))
            matches = [
                match
                for start, end in windows
                for match in regex.finditer(text, start, end)
            ]
            windows = [match.span() for match in matches]
        return matches

    return extract
