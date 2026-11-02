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


@pytest.fixture
def shell_closure(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Provide a shell dependency with a transitive data input outside the entry."""
    library = tmp_path / "lib"
    library.mkdir()
    helper = library / "setup.sh"
    helper.write_text("cat lib/data.json\nexit 99\n", encoding="utf-8")
    data = library / "data.json"
    data.write_text("{}", encoding="utf-8")
    return tmp_path / "entry.sh", helper, data


@pytest.mark.parametrize(
    "statement",
    [
        "source \\\nlib/setup.sh\n",
        "source lib/set\\\nup.sh\n",
        'source "lib/set\\\nup.sh"\n',
        "sou\\\nrce lib/setup.sh\n",
        "source \\\nlib/set\\\nup.sh;true\n",
    ],
    ids=["source-argument", "split-word", "double-quoted", "command", "combined"],
)
def test_shell_closure_follows_continued_source(
    shell_closure: tuple[Path, Path, Path], statement: str
) -> None:
    """Only continued source words refer to the helper and its transitive data."""
    entry, helper, data = shell_closure
    entry.write_text(statement, encoding="utf-8")
    assert_that(local_inputs(entry.parent, {entry})).contains(helper, data)


@pytest.mark.parametrize(
    "statement",
    [
        "source 'lib/set\\\nup.sh'\n",
        "# source lib/set\\\n#up.sh\n",
        "cat <<'EOF'\nlib/set\\\nup.sh\nEOF\n",
        "echo lib/set\\\\\nup.sh\n",
    ],
    ids=["single-quoted", "comment", "quoted-heredoc", "escaped-backslash"],
)
def test_shell_closure_keeps_literal_backslash_newlines(
    shell_closure: tuple[Path, Path, Path], statement: str
) -> None:
    """Literal backslashes must not manufacture a nonexistent source edge."""
    entry, helper, data = shell_closure
    entry.write_text(statement, encoding="utf-8")
    assert_that(local_inputs(entry.parent, {entry})).does_not_contain(helper, data)


@pytest.mark.parametrize(
    "prefix",
    [
        "echo name#suffix;",
        "echo ${x#prefix};",
        "echo $((1 << 2));",
        "((1 << 2));",
        "echo $((1 << (2 + 1)));",
        "echo $\\\n((1 << 2));",
        "cat <<'EOF'\nit's literal data\nEOF\n",
        "# it's a comment\n",
        "true;# it's a comment\n",
    ],
)
def test_shell_closure_preserves_context_before_continued_source(
    shell_closure: tuple[Path, Path, Path], prefix: str
) -> None:
    """Word hashes, arithmetic and preceding quotes cannot hide a source edge."""
    entry, helper, data = shell_closure
    entry.write_text(prefix + "source lib/set\\\nup.sh\n", encoding="utf-8")
    assert_that(local_inputs(entry.parent, {entry})).contains(helper, data)


@pytest.mark.parametrize("operator", [";", "&&", "||", "|", "&"])
def test_shell_closure_splits_adjacent_operators(
    shell_closure: tuple[Path, Path, Path], operator: str
) -> None:
    """Operators adjoining a literal path cannot hide its transitive inputs."""
    entry, helper, data = shell_closure
    entry.write_text(f"source lib/setup.sh{operator}true\n", encoding="utf-8")
    assert_that(local_inputs(entry.parent, {entry})).contains(helper, data)


@pytest.mark.parametrize(
    "marker", ["'EOF'", '"EOF"', "E'OF'", '"E"OF', "EOF", "-EOF", "- EOF", "-\\EOF"]
)
def test_shell_closure_handles_heredoc_data_and_expansions(
    shell_closure: tuple[Path, Path, Path], marker: str
) -> None:
    """Heredoc apostrophes are data; literal and executable inputs stay covered."""
    entry, helper, data = shell_closure
    entry.write_text(
        f"cat <<{marker} # header comment\n"
        "it's data\n$(source lib/setup.sh)\n"
        "EOF\nsource lib/setup.sh;true\n",
        encoding="utf-8",
    )
    assert_that(local_inputs(entry.parent, {entry})).contains(helper, data)


def test_shell_closure_retains_unquoted_heredoc_execution(
    shell_closure: tuple[Path, Path, Path],
) -> None:
    """Command substitution inside an unquoted heredoc remains an input edge."""
    entry, helper, data = shell_closure
    entry.write_text("cat <<EOF\nit's $(source lib/setup.sh)\nEOF\n", encoding="utf-8")
    assert_that(local_inputs(entry.parent, {entry})).contains(helper, data)


@pytest.mark.parametrize(
    "statement",
    [
        "cat <<EOF\n$(source lib/setup.sh)\nEOF\n",
        "cat <<EOF\n$(source lib/set\\\nup.sh)\nEOF\n",
        'cat <<EOF\n$(source "lib/set\\\nup.sh")\nEOF\n',
        "cat <<EOF\nit's $(source lib/se\\\nt\\\nup.sh)\nEOF\n",
        "cat <<EOF\n$(sou\\\nrce \\\nlib/set\\\nup.sh)\nEOF\n",
        "cat <<-EOF\n\t$(source lib/set\\\nup.sh)\n\tEOF\n",
        "cat <<-EOF\n\t$(source lib/set\\\n\tup.sh)\n\tEOF\n",
        (
            "cat <<'FIRST' <<-SECOND\nit's literal\nFIRST\n"
            "\t$(source lib/set\\\nup.sh)\n\tSECOND\n"
        ),
        "cat <<EOF\n$(source lib/set\\\nup.sh)\\\n\nEOF\n",
        "cat <<EOF\n$(source lib/set\\\nup.sh)\nE\\\nOF\n",
    ],
    ids=[
        "unsplit-control",
        "split-word",
        "double-quoted-word",
        "repeated-with-apostrophe",
        "command-and-argument",
        "tab-stripped",
        "tab-stripped-continuation",
        "multiple-heredocs",
        "continued-line-end",
        "continued-delimiter",
    ],
)
def test_shell_closure_follows_expandable_heredoc_continuations(
    shell_closure: tuple[Path, Path, Path], statement: str
) -> None:
    """Only the heredoc command names the helper and its transitive data."""
    entry, helper, data = shell_closure
    entry.write_text(statement, encoding="utf-8")
    assert_that(local_inputs(entry.parent, {entry})).contains(helper, data)


@pytest.mark.parametrize("marker", ["'EOF'", '"EOF"', "E'OF'", "\\EOF", "-'EOF'"])
def test_shell_closure_keeps_quoted_heredoc_continuations_literal(
    shell_closure: tuple[Path, Path, Path], marker: str
) -> None:
    """Quoted heredocs cannot manufacture a joined executable filename."""
    entry, helper, data = shell_closure
    entry.write_text(
        f"cat <<{marker}\n$(source lib/se\\\nt\\\nup.sh)\nEOF\n",
        encoding="utf-8",
    )
    assert_that(local_inputs(entry.parent, {entry})).does_not_contain(helper, data)


@pytest.mark.parametrize("backslashes", [2, 3, 4])
def test_shell_closure_preserves_escaped_heredoc_backslashes(
    shell_closure: tuple[Path, Path, Path], backslashes: int
) -> None:
    """Escaped backslashes cannot turn a different path into the helper."""
    entry, helper, data = shell_closure
    body = "$(source lib/set" + "\\" * backslashes + "\nup.sh)\n"
    entry.write_text("cat <<EOF\n" + body + "EOF\n", encoding="utf-8")
    assert_that(local_inputs(entry.parent, {entry})).does_not_contain(helper, data)


@pytest.mark.parametrize("backslashes", [2, 4])
def test_shell_closure_keeps_heredoc_boundary_after_escaped_backslashes(
    shell_closure: tuple[Path, Path, Path], backslashes: int
) -> None:
    """An escaped backslash cannot join the delimiter and hide the next command."""
    entry, helper, data = shell_closure
    body = "literal" + "\\" * backslashes + "\n"
    entry.write_text(
        "cat <<EOF\n" + body + "EOF\nsource lib/setup.sh\n", encoding="utf-8"
    )
    assert_that(local_inputs(entry.parent, {entry})).contains(helper, data)


@pytest.mark.parametrize(
    "prefix",
    [
        "[ $# -gt 0 ] && ",
        "echo ${#x};",
        "echo word#suffix;",
        "echo \\#;",
        "echo '#';",
        'echo "#";',
        "echo $\\\n#;",
        "# ordinary comment\n",
        "true;# adjacent operator comment\n",
    ],
    ids=[
        "positional-count",
        "parameter-length",
        "word-hash",
        "escaped-hash",
        "single-quoted-hash",
        "double-quoted-hash",
        "continued-special-parameter",
        "comment-newline",
        "operator-comment-newline",
    ],
)
def test_shell_closure_follows_source_after_literal_hashes(
    shell_closure: tuple[Path, Path, Path], prefix: str
) -> None:
    """A literal hash cannot hide the only helper reference later on the line."""
    entry, helper, data = shell_closure
    entry.write_text(prefix + "source lib/setup.sh\n", encoding="utf-8")
    assert_that(local_inputs(entry.parent, {entry})).contains(helper, data)


@pytest.mark.parametrize("prefix", ["#", "echo ok #", "true;#", "true&&#", "true|#"])
def test_shell_closure_ignores_source_inside_comments(
    shell_closure: tuple[Path, Path, Path], prefix: str
) -> None:
    """Genuine comments still hide paths after whitespace or shell operators."""
    entry, helper, data = shell_closure
    entry.write_text(prefix + " source lib/setup.sh\n", encoding="utf-8")
    assert_that(local_inputs(entry.parent, {entry})).does_not_contain(helper, data)


@pytest.mark.parametrize("body", ["source lib/setup.sh\n", "$(source lib/set\\\n"])
def test_shell_closure_rejects_unterminated_heredoc(
    shell_closure: tuple[Path, Path, Path],
    body: str,
) -> None:
    """An unknown heredoc boundary fails closed instead of dropping the rest."""
    entry, _, _ = shell_closure
    entry.write_text("cat <<EOF\n" + body, encoding="utf-8")
    with pytest.raises(ValueError, match="heredoc"):
        local_inputs(entry.parent, {entry})


@pytest.mark.parametrize(
    "prefix",
    [
        "echo '<<' '#'\n",
        "#it's a comment\n",
        'cat <<<"it\'s data";true\n',
        (
            "cat <<'FIRST' <<-SECOND\nit's literal lib/setup.sh\nFIRST\n"
            "\t$(source lib/setup.sh)\n\tSECOND\n"
        ),
    ],
)
def test_shell_closure_preserves_quoted_words_and_multiple_heredocs(
    shell_closure: tuple[Path, Path, Path], prefix: str
) -> None:
    """Only unquoted redirection operators introduce heredoc bodies."""
    entry, helper, data = shell_closure
    entry.write_text(prefix + "source lib/setup.sh\n", encoding="utf-8")
    assert_that(local_inputs(entry.parent, {entry})).contains(helper, data)


@pytest.mark.parametrize("prefix", ["", "echo $((1 << 2));", "echo '(('; "])
@pytest.mark.parametrize("marker", ["EOF", "E\\\nOF"])
@pytest.mark.parametrize("variable", ["$UNKNOWN", "$\\\nUNKNOWN", "$\\\nUN\\\nKNOWN"])
def test_shell_closure_fails_closed_on_dynamic_heredoc_inputs(
    shell_closure: tuple[Path, Path, Path],
    prefix: str,
    marker: str,
    variable: str,
) -> None:
    """Expandable heredocs cannot silently hide unknown executable inputs."""
    entry, _, _ = shell_closure
    entry.write_text(
        prefix + f'cat <<{marker}\n$(source "{variable}")\nEOF\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="dynamic heredoc"):
        local_inputs(entry.parent, {entry})
