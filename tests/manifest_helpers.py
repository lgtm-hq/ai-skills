"""Offline regression fixtures scoped to manifest authoring and vendor pin tests."""

import json
import re
import shutil
import subprocess  # nosec B404 - bounded local lint process, no shell
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from assertpy import assert_that

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def author_skills(tmp_path: Path) -> None:
    """Supply the actual first-party payloads declared by publication fixtures."""
    shutil.copytree(src=SCRIPTS_DIR.parent / "skills", dst=tmp_path / "skills")


@dataclass
class VendorPinMatch:
    """Merged recursive captures with source spans for pin-update assertions."""

    groups: dict[str, str]
    spans: dict[str, tuple[int, int]]

    def groupdict(self) -> dict[str, str]:
        """Return the captures merged across all recursive stages."""
        return self.groups

    def __getitem__(self, name: str) -> str:
        """Read one merged capture."""
        return self.groups[name]

    def span(self, name: str) -> tuple[int, int]:
        """Locate a capture in the original manifest."""
        return self.spans[name]


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
def vendor_pin_matches() -> Callable[[str], list[VendorPinMatch]]:
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

    assert_that(manager["matchStringsStrategy"]).is_equal_to("recursive")

    def extract(text: str) -> list[VendorPinMatch]:
        """Match each substring independently and merge groups like Renovate.

        Mirrors processRecursive/mergeGroups in Renovate's custom/regex manager:
        each next pattern receives match[0], including its own start/end anchors;
        captures from earlier stages survive unless overwritten by a later one.
        Source offsets are bookkeeping for the real pin-edit regression only.
        """
        windows = [(text, 0, VendorPinMatch({}, {}))]
        for pattern in manager["matchStrings"]:
            regex = re.compile(pattern.replace("(?<", "(?P<"))
            next_windows = []
            for content, offset, previous in windows:
                for match in regex.finditer(content):
                    groups = match.groupdict()
                    spans = {
                        name: (offset + match.start(name), offset + match.end(name))
                        for name, value in groups.items()
                        if value is not None
                    }
                    merged = VendorPinMatch(
                        groups={**previous.groups, **groups},
                        spans={**previous.spans, **spans},
                    )
                    next_windows.append((match[0], offset + match.start(), merged))
            windows = next_windows
        return [merged for _, _, merged in windows]

    return extract
