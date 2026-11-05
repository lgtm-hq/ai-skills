"""Local fake forge and consumer repositories for the authoring command tests.

The generic fixture vendors under ``tests/fixtures/vendors`` are served by a
patched fetcher keyed by repository, refs resolve through a patched resolver,
and network and subprocess use fail the test.
"""

import io
import json
import shutil
import subprocess  # nosec B404 - only patched to prove it is never called
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures/vendors"
REPOS = {
    "fixture-org/manifest": "manifest",
    "fixture-org/manifestless": "manifestless",
    "fixture-org/reexporter": "reexporter",
}
PINS = {
    "fixture-org/manifest": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
    "fixture-org/manifestless": "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c",
    "fixture-org/reexporter": "2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f",
}
ENGINE_SHA = "abcdef0123456789abcdef0123456789abcdef01"


class Forge:
    """Serve fixture vendor trees by repository, recording every request.

    Attributes:
        trees: Repository to served directory.
        fetched: ``repo@sha`` acquisitions.
        resolved: ``(repo, displayRef, branch)`` resolutions.
        pins: Repository to the SHA every ref resolves to.
    """

    def __init__(self, base: Path) -> None:
        self.trees = {repo: base / name for repo, name in REPOS.items()}
        self.fetched: list[str] = []
        self.resolved: list[tuple[str, str | None, str | None]] = []
        self.pins = dict(PINS)

    def fetch(self, *, vendor: Any, dest: Path) -> None:
        """Copy the served tree instead of downloading a tarball.

        Args:
            vendor: Requested pin.
            dest: New directory receiving the tree.
        """
        self.fetched.append(f"{vendor.repo}@{vendor.sha}")
        shutil.copytree(self.trees[vendor.repo], dest, symlinks=True)

    def resolve(self, *, vendor: Any) -> str:
        """Resolve any ref of a served repository to its pin.

        Args:
            vendor: Registry vendor carrying ``displayRef`` and ``branch``.

        Returns:
            The repository's fixture pin.
        """
        self.resolved.append((vendor.repo, vendor.display_ref, vendor.branch))
        return self.pins[vendor.repo]


def _forbidden(*_args: object, **_kwargs: object) -> None:
    """Fail on network or subprocess use.

    Raises:
        AssertionError: Always.
    """
    raise AssertionError("network or subprocess use during an authoring command")


@pytest.fixture
def forge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Forge:
    """Patch acquisition and ref resolution; forbid network and subprocesses.

    Args:
        tmp_path: Test directory receiving a private copy of the fixtures.
        monkeypatch: Patcher.

    Returns:
        The fake forge.
    """
    from ai_skills_engine.bake import vendor_plugins
    from ai_skills_engine.vendors import repin

    served = tmp_path / "forge"
    shutil.copytree(FIXTURES, served)
    fake = Forge(served)
    monkeypatch.setattr(vendor_plugins, "_fetch_vendor_tree", fake.fetch)
    monkeypatch.setattr(vendor_plugins, "_http_get_bytes", _forbidden)
    monkeypatch.setattr(repin, "resolve_upstream_sha", fake.resolve)
    monkeypatch.setattr(repin, "_github_json", _forbidden)
    monkeypatch.setattr("socket.socket.connect", _forbidden)
    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, _forbidden)
    monkeypatch.setattr("os.system", _forbidden)
    return fake


@pytest.fixture
def consumer(tmp_path: Path) -> Path:
    """Create a consumer repository with one local skill and no vendors.

    Args:
        tmp_path: Test directory.

    Returns:
        Consumer root.
    """
    root = tmp_path / "consumer"
    (root / "skills/local").mkdir(parents=True)
    (root / "skills/local/SKILL.md").write_text(
        "---\nname: local\ndescription: Consumer fixture skill.\n---\n\n"
        "# local\n\nFollow the consumer steps.\n"
    )
    (root / "ai-skills.yaml").write_text(
        "---\n"
        "# Consumer fixture; comments survive add.\n"
        "apiVersion: ai-skills.dev/v1\n"
        "publisher:\n"
        "  id: consumer\n"
        "  repo: fixture-org/consumer\n"
        "packages:\n"
        "  - id: local\n"
        "    capabilities:\n"
        "      - id: local\n"
        "        path: skills/local\n"
        "exports: [local]\n"
        "policy:\n"
        "  provenance:\n"
        "    mode: strict\n"
    )
    return root


def run_cli(*arguments: str) -> tuple[int, str, str]:
    """Invoke the public engine CLI in process, capturing its output.

    Args:
        arguments: Command line after the program name.

    Returns:
        Exit status, stdout and stderr.
    """
    from ai_skills_engine import cli

    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            status = cli.main(list(arguments))
        except SystemExit as error:
            status = int(error.code or 0)
    return status, stdout.getvalue(), stderr.getvalue()


def validate_json(root: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    """Run ``validate --format json`` and parse its report.

    Args:
        root: Repository to validate.
        extra: Additional arguments.

    Returns:
        Exit status and the parsed report.
    """
    status, output, _ = run_cli(
        "validate", "--repo-root", str(root), "--format", "json", *extra
    )
    return status, json.loads(output)


def stage(report: dict[str, Any], name: str) -> dict[str, Any]:
    """Select one stage from a JSON report.

    Args:
        report: Parsed ``validate --format json`` output.
        name: Stage name.

    Returns:
        The stage record.
    """
    return next(item for item in report["stages"] if item["name"] == name)


def codes(report: dict[str, Any], name: str) -> list[str]:
    """List diagnostic codes of one stage.

    Args:
        report: Parsed report.
        name: Stage name.

    Returns:
        Codes in report order.
    """
    return [item["code"] for item in stage(report, name)["diagnostics"]]
