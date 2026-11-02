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
        repo / "tests/test_install_plane_gates.py",
        repo / "tests/conftest.py",
        repo / "scripts/ci/install_plane_changes.py",
        repo / "scripts/tool-versions.sh",
        repo / ".github/workflows/install-plane-spike.yml",
        repo / ".github/workflows/all-checks-gate.yml",
        repo / ".github/workflows/install-plane-release-gate.yml",
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
        'import importlib; MODULE = "helper"; importlib.import_module(MODULE)',
        'from importlib import import_module; MODULE = "helper"; import_module(MODULE)',
        'from importlib import import_module as load; MODULE = "helper"; load(MODULE)',
        (
            "from constants import MODULE; import importlib; "
            "importlib.import_module(MODULE)"
        ),
        "from constants import ALIAS; import importlib; importlib.import_module(ALIAS)",
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
    (source / "constants.py").write_text(
        'ALIAS = MODULE\nMODULE = "helper"\n', encoding="utf-8"
    )
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


@pytest.mark.parametrize(
    "reference",
    [
        'DATA = Path(__file__).parent / "../data.json"',
        'open("src/../data.json")',
        'DATA = Path(__file__).parent.joinpath("..", "data.json")',
    ],
)
def test_closure_normalizes_parent_paths(tmp_path: Path, reference: str) -> None:
    """Inventory membership uses normalized paths for constructed and literal reads."""
    source = tmp_path / "src"
    source.mkdir()
    entry = source / "entry.py"
    entry.write_text("from pathlib import Path\n" + reference, encoding="utf-8")
    data = tmp_path / "data.json"
    data.write_text("{}", encoding="utf-8")
    assert_that(local_inputs(tmp_path, {entry})).contains(data)


def test_closure_follows_shell_literals_without_executing(tmp_path: Path) -> None:
    """Source, dot, shell arguments and transitive reads enter the input closure."""
    entry = tmp_path / "entry.sh"
    entry.write_text(
        '#!/bin/bash\nsource "lib/setup.sh"\n. lib/pins.sh\n'
        'bash "lib/runner.sh"\npython3 lib/helper.py\n',
        encoding="utf-8",
    )
    library = tmp_path / "lib"
    library.mkdir()
    for name in ("setup.sh", "pins.sh", "runner.sh"):
        (library / name).write_text("cat lib/data.json\nexit 99\n", encoding="utf-8")
    helper = library / "helper.py"
    helper.write_text('open("lib/data.json")', encoding="utf-8")
    data = library / "data.json"
    data.write_text("{}", encoding="utf-8")
    assert_that(local_inputs(tmp_path, {entry})).contains(
        entry, helper, data, *library.glob("*.sh")
    )
