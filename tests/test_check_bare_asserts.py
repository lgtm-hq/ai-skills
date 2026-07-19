"""Tests for the AST-based bare-``assert`` checker.

The checker parses each ``tests/`` module with :mod:`ast` and reports
every :class:`ast.Assert` node. These tests exercise the behavior the
old ``grep`` scan could not: prose inside a docstring that mentions an
assertion must not be flagged, while both ``assert expr`` and
``assert(expr)`` statements must be caught.
"""

from __future__ import annotations

from pathlib import Path

from assertpy import assert_that
from check_bare_asserts import find_bare_asserts
from loguru import logger


def _write_module(
    tmp_path: Path,
    source: str,
) -> Path:
    """Write a Python module into a temp test tree.

    Args:
        tmp_path: Pytest temporary directory acting as fake ``tests/``.
        source: Module source to write into ``test_sample.py``.

    Returns:
        The temp tree root to scan.
    """
    (tmp_path / "test_sample.py").write_text(source, encoding="utf-8")
    logger.debug("Wrote test_sample.py:\n{}", source)
    return tmp_path


def test_real_bare_assert_is_caught(
    tmp_path: Path,
) -> None:
    """Flag a genuine ``assert expr`` statement in a test module."""
    root = _write_module(
        tmp_path=tmp_path,
        source="def test_x() -> None:\n    assert 1 == 1\n",
    )

    violations = find_bare_asserts(root=root)

    assert_that(violations).is_length(1)
    assert_that(violations[0]).contains("test_sample.py:2")
    logger.info("[TEST] bare assert flagged: {}", violations[0])


def test_assert_in_docstring_is_not_flagged(
    tmp_path: Path,
) -> None:
    """Do not flag the word ``assert`` when it lives inside a docstring."""
    source = (
        '"""Module docstring.\n\n'
        "Example prose describing behavior:\n"
        "assert this line is ignored by the AST walk\n"
        "assert (also ignored inside the string)\n"
        '"""\n\n'
        "from assertpy import assert_that\n\n\n"
        "def test_x() -> None:\n"
        '    """assert mentioned in a function docstring."""\n'
        "    assert_that(1).is_equal_to(1)\n"
    )
    root = _write_module(tmp_path=tmp_path, source=source)

    violations = find_bare_asserts(root=root)

    assert_that(violations).is_empty()
    logger.info("[TEST] docstring asserts not flagged")


def test_assert_call_form_is_caught(
    tmp_path: Path,
) -> None:
    """Flag the ``assert(expr)`` parenthesized form as a bare assert."""
    root = _write_module(
        tmp_path=tmp_path,
        source="def test_x() -> None:\n    assert(1 == 1)\n",
    )

    violations = find_bare_asserts(root=root)

    assert_that(violations).is_length(1)
    assert_that(violations[0]).contains("test_sample.py:2")
    logger.info("[TEST] assert(...) form flagged: {}", violations[0])


def test_clean_file_passes(
    tmp_path: Path,
) -> None:
    """Report no violations for a module that uses only assertpy."""
    source = (
        "from assertpy import assert_that\n\n\n"
        "def test_x() -> None:\n"
        "    assert_that(1).is_equal_to(1)\n"
    )
    root = _write_module(tmp_path=tmp_path, source=source)

    violations = find_bare_asserts(root=root)

    assert_that(violations).is_empty()
    logger.info("[TEST] clean assertpy module passes")
