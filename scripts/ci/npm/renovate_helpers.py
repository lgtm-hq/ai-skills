"""Offline regression fixtures scoped to manifest authoring and vendor pin tests."""

import json
import os
import shutil
import subprocess  # nosec B404 - bounded local lint process, no shell
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that

SCRIPTS_DIR = Path(__file__).resolve().parents[2]


@dataclass
class VendorPinMatch:
    """Production JSONata captures with CST spans for pin-update assertions."""

    groups: dict[str, str]
    spans: dict[str, tuple[int, int]]

    def groupdict(self) -> dict[str, str]:
        """Return the fields extracted by production Renovate."""
        return self.groups

    def __getitem__(self, name: str) -> str:
        """Read one production capture."""
        return self.groups[name]

    def span(self, name: str) -> tuple[int, int]:
        """Locate a capture in the original manifest."""
        return self.spans[name]


@pytest.fixture
def author_skills(tmp_path: Path) -> None:
    """Supply real first-party payloads for compatibility publication."""
    shutil.copytree(src=SCRIPTS_DIR.parent / "skills", dst=tmp_path / "skills")


@cache
def _renovate_modules() -> dict[str, str]:
    """Resolve exact locked test dependencies without acquiring or writing them.

    Returns:
        Module entry paths from a prepared installation.
    """
    package = SCRIPTS_DIR.parent / "npm" / "ai-skills"
    versions = json.loads((package / "package.json").read_text())["devDependencies"]
    production = json.loads(
        (
            SCRIPTS_DIR.parent / "tests/fixtures/manifest/renovate/sources.json"
        ).read_text()
    )["dependencies"]
    prepared = Path(
        os.environ.get("RENOVATE_TEST_NODE_MODULES", package / "node_modules")
    )
    modules = {}
    for name in ("@sindresorhus/is", "handlebars", "jsonata", "yaml", "zod"):
        assert_that(versions[name]).is_equal_to(production[name])
        directory = prepared / name
        metadata = json.loads((directory / "package.json").read_text())
        assert_that(metadata["version"]).is_equal_to(versions[name])
        main = metadata.get("main") or metadata["exports"]["default"]
        modules[name] = str((directory / main).resolve())
    return modules


@cache
def _run_renovate(text: str, updates: str = "[]") -> dict[str, Any]:
    """Execute verified upstream manager/parser/updater snapshots offline.

    Args:
        text: Source YAML to extract and optionally update.
        updates: JSON array of production upgrade inputs.

    Returns:
        Captures, dependencies, attempted updates and final source.
    """
    manager = next(
        item
        for item in json.loads((SCRIPTS_DIR.parent / "renovate.json").read_text())[
            "customManagers"
        ]
        if item.get("datasourceTemplate") == "git-refs"
    )
    result = subprocess.run(  # nosec B603 B607 - fixed local tools/fixtures; no shell or acquisition
        [
            "bun",
            str(SCRIPTS_DIR.parent / "tests/fixtures/manifest/renovate-runner.ts"),
        ],
        input=json.dumps(
            {
                "text": text,
                "config": manager,
                "modules": _renovate_modules(),
                "updates": json.loads(updates),
            }
        ),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert_that(result.returncode).described_as(result.stderr).is_zero()
    output: object = json.loads(result.stdout)
    if not isinstance(output, dict):
        raise TypeError("Renovate runner must return a JSON object")
    return output


@pytest.fixture
def renovate_run() -> Callable[..., dict[str, Any]]:
    """Return the offline production parser/query/update harness."""
    return _run_renovate


@pytest.fixture
def vendor_pin_matches() -> Callable[[str], list[VendorPinMatch]]:
    """Extract using production Renovate with its actual strict:false parser.

    Returns:
        Native extractor with source spans for ordinary digest scalars.
    """

    def extract(text: str) -> list[VendorPinMatch]:
        """Run the configured manager rather than a handwritten query mock."""
        return [
            VendorPinMatch(
                groups=item["groups"],
                spans={key: tuple(span) for key, span in item["spans"].items()},
            )
            for item in _run_renovate(text)["matches"]
        ]

    return extract
