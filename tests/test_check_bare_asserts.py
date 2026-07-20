"""Tests for the AST-based bare-``assert`` checker.

The checker parses each ``tests/`` module with :mod:`ast` and reports
every :class:`ast.Assert` node. These tests exercise the behavior the
old ``grep`` scan could not: prose inside a docstring that mentions an
assertion must not be flagged, while both ``assert expr`` and
``assert(expr)`` statements must be caught.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from assertpy import assert_that
from check_bare_asserts import find_bare_asserts, main
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


def test_unreadable_file_reports_read_violation(
    tmp_path: Path,
) -> None:
    """Report a ``cannot read file`` violation for undecodable bytes."""
    (tmp_path / "test_binary.py").write_bytes(b"\xff\xfe\x00bad utf-8\x00")

    violations = find_bare_asserts(root=tmp_path)

    assert_that(violations).is_length(1)
    assert_that(violations[0]).contains("test_binary.py:0:")
    assert_that(violations[0]).contains("cannot read file")
    logger.info("[TEST] unreadable file reported: {}", violations[0])


def test_syntax_error_reports_parse_violation(
    tmp_path: Path,
) -> None:
    """Report a ``cannot parse file`` violation for broken syntax."""
    root = _write_module(
        tmp_path=tmp_path,
        source="def broken(:\n",
    )

    violations = find_bare_asserts(root=root)

    assert_that(violations).is_length(1)
    assert_that(violations[0]).contains("test_sample.py:1")
    assert_that(violations[0]).contains("cannot parse file")
    logger.info("[TEST] syntax error reported: {}", violations[0])


def test_main_rejects_missing_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exit 1 with a stderr message when the root directory is missing."""
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(sys, "argv", ["check_bare_asserts.py", str(missing)])

    exit_code = main()

    captured = capsys.readouterr()
    assert_that(exit_code).is_equal_to(1)
    assert_that(captured.err).contains("Directory not found")
    logger.info("[TEST] missing root rejected with exit code 1")


def test_main_reports_violations_with_banner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exit 1 and print the banner plus ``path:line:`` violation lines."""
    root = _write_module(
        tmp_path=tmp_path,
        source="def test_x() -> None:\n    assert 1 == 1\n",
    )
    monkeypatch.setattr(sys, "argv", ["check_bare_asserts.py", str(root)])

    exit_code = main()

    captured = capsys.readouterr()
    assert_that(exit_code).is_equal_to(1)
    assert_that(captured.out).contains(
        "Bare-assert check found violations (see each line for details):",
    )
    assert_that(captured.out).contains("test_sample.py:2: bare assert statement")
    logger.info("[TEST] main reports banner and violation lines")
