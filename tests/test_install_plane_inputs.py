"""Keep the isolated harness's entire local input closure in its CI trigger list."""

from __future__ import annotations

from pathlib import Path

import pytest
from assertpy import assert_that
from ci.install_plane_inputs import MANIFEST, local_inputs, matches, patterns


def test_harness_input_closure() -> None:
    """A new local import or literal repository file read must trigger spike CI."""
    repo = Path(__file__).resolve().parents[1]
    spike = repo / "research/install-plane-spike"
    entrypoints = {
        *spike.glob("tests/*.py"),
        *spike.glob("scripts/*"),
        repo / "tests/test_install_plane_parity.py",
        repo / "tests/test_install_plane_inputs.py",
        repo / "tests/conftest.py",
        repo / "scripts/ci/install_plane_changes.py",
        repo / "scripts/tool-versions.sh",
        repo / ".github/workflows/install-plane-spike.yml",
        repo / ".gitattributes",
        repo / "pyproject.toml",
        repo / "uv.lock",
        repo / MANIFEST,
    }
    globs = patterns(repo)
    missing = sorted(
        path.relative_to(repo).as_posix()
        for path in local_inputs(repo, entrypoints)
        if not matches(path.relative_to(repo).as_posix(), globs)
    )
    assert_that(missing).described_as("Uncovered harness inputs").is_empty()


@pytest.mark.parametrize(
    "statement",
    [
        "import helper",
        "from helper import DATA",
        'import importlib; importlib.import_module("helper")',
        (
            'import importlib.util; importlib.util.spec_from_file_location("loaded", '
            'Path(__file__).parent / "src/helper.py")'
        ),
        'import runpy; runpy.run_path("src/helper.py")',
    ],
)
def test_closure_follows_new_dependencies(tmp_path: Path, statement: str) -> None:
    """Resolve new imports and data reads outside the committed spike subtree.

    Args:
        tmp_path: Isolated synthetic repository.
        statement: Supported local import or literal file-loading expression.
    """
    source = tmp_path / "src"
    source.mkdir()
    helper = source / "helper.py"
    helper.write_text(
        "import nested\nfrom pathlib import Path\n"
        'DATA = Path(__file__).parent / "data.json"\n',
        encoding="utf-8",
    )
    nested = source / "nested.py"
    nested.write_text('"""Transitive local dependency."""\n', encoding="utf-8")
    data = source / "data.json"
    data.write_text("{}", encoding="utf-8")
    entry = tmp_path / "test_harness.py"
    entry.write_text(
        "import sys\nfrom pathlib import Path\n"
        'sys.path.insert(0, str(Path(__file__).parent / "src"))\n' + statement,
        encoding="utf-8",
    )
    assert_that(local_inputs(tmp_path, {entry})).contains(entry, helper, nested, data)
