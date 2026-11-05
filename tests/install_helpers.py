"""Offline install-plane fixtures built by the real artifact builder."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ai_skills_engine import cli

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "artifacts/golden"
EXPECTED = FIXTURES / "install/expected-kept.json"
TWO_HOP = FIXTURES / "provenance/two-hop"
X_ORIGIN = "github.com/fixture/x"

type Edit = Callable[[dict[str, Any], Path], None]


def _fail(*_args: object, **_kwargs: object) -> None:
    """Reject any network or build-plane resolution call from the install plane."""
    pytest.fail("The install plane must not resolve or fetch")


def forbid_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject failing resolver, fetcher, subprocess and network boundaries.

    Call it after any builder setup: from then on, resolution fails the test.

    Args:
        monkeypatch: Patcher; every boundary fails the test if called.
    """
    from ai_skills_engine import source_cache
    from ai_skills_engine.commands import sources
    from ai_skills_engine.inventory import load as inventory_load
    from ai_skills_engine.selection import load as selection_load

    monkeypatch.setattr("socket.socket.connect", _fail)
    monkeypatch.setattr("socket.create_connection", _fail)
    monkeypatch.setattr("urllib.request.urlopen", _fail)
    monkeypatch.setattr("subprocess.Popen", _fail)
    monkeypatch.setattr(selection_load, "load_inputs", _fail)
    monkeypatch.setattr(inventory_load, "load_inventory", _fail)
    monkeypatch.setattr(sources, "materialize_sources", _fail)
    monkeypatch.setattr(sources, "build_lock", _fail)
    monkeypatch.setattr(source_cache.SourceCache, "default", _fail)


@pytest.fixture
def golden(tmp_path: Path) -> Path:
    """Copy the builder's golden artifact so tests may corrupt it.

    Args:
        tmp_path: Private directory.

    Returns:
        Writable artifact directory.
    """
    target = tmp_path / "golden"
    shutil.copytree(GOLDEN, target)
    return target


@pytest.fixture
def consumer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run from an empty directory with an injected home and no XDG config.

    Args:
        tmp_path: Private directory.
        monkeypatch: Environment patcher.

    Returns:
        Injected home directory.
    """
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("AI_SKILLS_ARTIFACTS", raising=False)
    monkeypatch.chdir(work)
    return home


def profile_path(home: Path) -> Path:
    """Return the default profile location under an injected home.

    Args:
        home: Injected home.

    Returns:
        ``~/.config/ai-skills/selection.yaml``.
    """
    return home / ".config/ai-skills/selection.yaml"


def run(
    capsys: pytest.CaptureFixture[str], *args: str
) -> tuple[int, dict[str, Any] | None, str]:
    """Run an engine command with ``--json`` and capture its result.

    Args:
        capsys: Output capture.
        *args: Command and arguments.

    Returns:
        Exit status, decoded report (None on failure) and stderr.
    """
    status = cli.main([*args, "--json"])
    captured = capsys.readouterr()
    report = json.loads(captured.out) if status == 0 else None
    return status, report, captured.err


def expected_cases() -> list[dict[str, Any]]:
    """Load the builder-recorded expected kept sets for the golden artifact.

    Returns:
        Cases with ``exclude``, ``deny`` and ``kept`` or ``error``.
    """
    return list(json.loads(EXPECTED.read_text())["cases"])


def two_hop_source(root: Path, edit: Edit | None = None) -> Path:
    """Stage X -> Y -> Z where Z re-exports Y's re-export of X.

    Z adds ``own`` (no X ancestry) and ``helper`` (keeps only X's resource in
    its ``_shared/`` copy) beside ``first``/``second`` (which require Y's
    X-derived capabilities).

    Args:
        root: Empty directory for the snapshots.
        edit: Optional change to Z (manifest document, snapshot root).

    Returns:
        Snapshot root containing x, y and z.
    """
    from ai_skills_engine.manifest.edit import dump_document
    from ai_skills_engine.manifest.load import read_document

    shutil.copytree(TWO_HOP, root)
    z = root / "z"
    for name in ("own", "helper"):
        (z / "skills" / name).mkdir(parents=True)
        (z / "skills" / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Fixture.\n---\n\n# {name}\n"
        )
    path = z / "ai-skills.yaml"
    document = read_document(path)
    document["policy"] = {"provenance": {"mode": "strict", "acceptAttestations": False}}
    document["packages"][0]["capabilities"] += [
        {"id": "own", "path": "skills/own"},
        {
            "id": "helper",
            "path": "skills/helper",
            "resources": ["x/tools:resource/script"],
        },
    ]
    document["exports"] = ["tools", "y/tools", "x/tools"]
    if edit is not None:
        edit(document, z)
    path.write_text(dump_document(document))
    return root


def build_two_hop(root: Path, destination: Path, edit: Edit | None = None) -> Path:
    """Build the X -> Y -> Z artifact with the real builder.

    Args:
        root: Empty directory for the snapshots.
        destination: Artifact output directory.
        edit: Optional change to Z's manifest (builder-side selection).

    Returns:
        Artifact directory.
    """
    from artifact_helpers import bake_fixture

    source = two_hop_source(root, edit)
    bake_fixture(
        root=source / "z",
        destination=destination,
        roots={"y": source / "y", "y/x": source / "x"},
    )
    return destination


def builder_kept(directory: Path) -> dict[str, list[str]]:
    """Read the kept sets a builder run recorded in its catalog index.

    Args:
        directory: Artifact directory.

    Returns:
        Sorted capability IDs and sorted resource IDs.
    """
    index = json.loads((directory / "index.json").read_text())
    return {
        "capabilities": sorted(
            item["id"]
            for package in index["packages"]
            for item in package["capabilities"]
        ),
        "resources": sorted(
            item["id"] for package in index["packages"] for item in package["resources"]
        ),
    }
