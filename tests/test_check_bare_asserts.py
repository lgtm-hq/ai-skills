"""Tests for the bare-assert AST checker."""

from __future__ import annotations

from pathlib import Path

from assertpy import assert_that
from check_bare_asserts import find_bare_asserts
from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_module(
    tmp_path: Path,
    body: str,
    name: str = "test_module.py",
) -> Path:
    """Write a Python module into a temp tree.

    Args:
        tmp_path: Pytest temporary directory acting as fake tests root.
        body: Source text to write into ``name``.
        name: File name to write beneath ``tmp_path``.

    Returns:
        The temp tree root to scan.
    """
    (tmp_path / name).write_text(body, encoding="utf-8")
    logger.debug("Wrote {} ({} bytes)", name, len(body))
    return tmp_path


def test_bare_assert_statement_is_flagged(
    tmp_path: Path,
) -> None:
    """Flag an executable ``assert expr`` statement in a test file."""
    body = (
        '"""Module docstring."""\n'
        "\n"
        "def test_case() -> None:\n"
        '    """Case docstring."""\n'
        "    assert 1 == 1\n"
    )
    root = _write_module(tmp_path=tmp_path, body=body)

    violations = find_bare_asserts(root=root)

    assert_that(violations).is_length(1)
    assert_that(violations[0]).contains("test_module.py:5")
    assert_that(violations[0]).contains("bare `assert`")
    logger.info("[TEST] bare assert flagged: {}", violations[0])


def test_assert_call_form_is_flagged(
    tmp_path: Path,
) -> None:
    """Flag the ``assert(expr)`` parenthesised form as well."""
    body = (
        '"""Module docstring."""\n'
        "\n"
        "def test_case() -> None:\n"
        '    """Case docstring."""\n'
        "    assert(1 == 1)\n"
    )
    root = _write_module(tmp_path=tmp_path, body=body)

    violations = find_bare_asserts(root=root)

    assert_that(violations).is_length(1)
    assert_that(violations[0]).contains("test_module.py:5")
    logger.info("[TEST] assert() form flagged: {}", violations[0])


def test_docstring_example_is_not_flagged(
    tmp_path: Path,
) -> None:
    """Ignore ``assert`` tokens that live inside a docstring."""
    body = (
        '"""Module docstring with an example.\n'
        "\n"
        "Do not write:\n"
        "assert result == 5\n"
        '"""\n'
        "\n"
        "from assertpy import assert_that\n"
        "\n"
        "def test_case() -> None:\n"
        '    """Function docstring.\n'
        "\n"
        "    Example of the wrong pattern (documentation only):\n"
        "    assert result == 5\n"
        '    """\n'
        "    assert_that(1).is_equal_to(1)\n"
    )
    root = _write_module(tmp_path=tmp_path, body=body)

    violations = find_bare_asserts(root=root)

    assert_that(violations).is_empty()
    logger.info("[TEST] docstring example not flagged")


def test_comment_with_assert_is_not_flagged(
    tmp_path: Path,
) -> None:
    """Ignore ``assert`` tokens that appear inside comments."""
    body = (
        '"""Module docstring."""\n'
        "\n"
        "from assertpy import assert_that\n"
        "\n"
        "def test_case() -> None:\n"
        '    """Case docstring."""\n'
        "    # assert 1 == 1  # this is a comment, not a statement\n"
        "    assert_that(1).is_equal_to(1)\n"
    )
    root = _write_module(tmp_path=tmp_path, body=body)

    violations = find_bare_asserts(root=root)

    assert_that(violations).is_empty()
    logger.info("[TEST] commented assert not flagged")


def test_clean_file_passes(
    tmp_path: Path,
) -> None:
    """Accept a test module that only uses ``assertpy.assert_that``."""
    body = (
        '"""Clean module."""\n'
        "\n"
        "from assertpy import assert_that\n"
        "\n"
        "def test_case() -> None:\n"
        '    """Uses only assertpy."""\n'
        "    assert_that(1).is_equal_to(1)\n"
        "    assert_that([1, 2]).contains(2)\n"
    )
    root = _write_module(tmp_path=tmp_path, body=body)

    violations = find_bare_asserts(root=root)

    assert_that(violations).is_empty()
    logger.info("[TEST] clean file passes")


def test_pytest_raises_is_not_flagged(
    tmp_path: Path,
) -> None:
    """Keep ``pytest.raises`` idioms unaffected; they are not ``Assert``."""
    body = (
        '"""Module."""\n'
        "\n"
        "import pytest\n"
        "from assertpy import assert_that\n"
        "\n"
        "def test_case() -> None:\n"
        '    """Uses pytest.raises."""\n'
        "    with pytest.raises(ValueError):\n"
        "        raise ValueError('boom')\n"
        "    assert_that(True).is_true()\n"
    )
    root = _write_module(tmp_path=tmp_path, body=body)

    violations = find_bare_asserts(root=root)

    assert_that(violations).is_empty()
    logger.info("[TEST] pytest.raises unaffected")


def test_syntax_error_is_reported(
    tmp_path: Path,
) -> None:
    """Report a parse failure so bad test files cannot silently pass."""
    body = "def broken(:\n    pass\n"
    root = _write_module(tmp_path=tmp_path, body=body, name="test_broken.py")

    violations = find_bare_asserts(root=root)

    assert_that(violations).is_length(1)
    assert_that(violations[0]).contains("cannot parse file")
    logger.info("[TEST] syntax error surfaced: {}", violations[0])


def test_skip_dirs_are_not_scanned(
    tmp_path: Path,
) -> None:
    """Skip vendored and generated directories entirely."""
    vendored = tmp_path / ".venv" / "site-packages"
    vendored.mkdir(parents=True)
    (vendored / "bad.py").write_text("assert 1 == 1\n", encoding="utf-8")

    violations = find_bare_asserts(root=tmp_path)

    assert_that(violations).is_empty()
    logger.info("[TEST] skip dirs excluded from scan")


def test_repository_tests_tree_passes() -> None:
    """The real ``tests/`` tree must satisfy the assertpy policy."""
    violations = find_bare_asserts(root=REPO_ROOT / "tests")

    assert_that(violations).is_empty()
    logger.info("[TEST] repository tests tree clean of bare asserts")
