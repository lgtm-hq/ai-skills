#!/usr/bin/env python3
"""Check that test modules use ``assertpy`` instead of bare ``assert``.

Enforces the owner-standard assertion policy (#88): every assertion in
``tests/`` must go through ``assertpy.assert_that(...)`` (``pytest.raises``
contexts remain as-is). The previous validator used a line-based ``grep``,
which false-positived on docstring examples such as::

    def test_something() -> None:
        \"\"\"Example.

        Do not write:
        assert result == 5

        Instead use assertpy.
        \"\"\"

This module walks each ``*.py`` file with :mod:`ast` and reports every
``ast.Assert`` node it finds. Because docstrings and comments never parse
to ``Assert`` nodes, they cannot false-positive.

Output stays CI-greppable: one ``path:line: message`` per violation on
stdout, and the process exits ``1`` on any hit (``0`` when clean).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SKIP_DIRS = frozenset(
    {
        "__pycache__",
        "build",
        "dist",
        "env",
        "node_modules",
        "test_samples",
        "venv",
    },
)


def _is_skipped(
    relative: Path,
) -> bool:
    """Report whether a relative path lies under a skipped directory.

    Args:
        relative: File path relative to the scan root.

    Returns:
        True when any parent directory is hidden (dot-prefixed) or a
        known vendored/generated directory.
    """
    return any(
        part.startswith(".") or part in SKIP_DIRS for part in relative.parts[:-1]
    )


def find_bare_asserts(
    root: Path,
) -> list[str]:
    """Find bare ``assert`` statements under a root.

    Args:
        root: Directory tree to scan for ``*.py`` files.

    Returns:
        A list of violation messages (``path:line: ...``); empty when
        every assertion goes through ``assertpy``.
    """
    violations: list[str] = []
    for py_file in sorted(root.rglob("*.py")):
        relative = py_file.relative_to(root)
        if _is_skipped(relative=relative):
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append(f"{relative}: cannot read file: {exc}")
            continue
        try:
            tree = ast.parse(source=source, filename=str(relative))
        except SyntaxError as exc:
            violations.append(
                f"{relative}:{exc.lineno or 0}: cannot parse file: {exc.msg}",
            )
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                violations.append(
                    f"{relative}:{node.lineno}: bare `assert` statement; "
                    f"use assertpy `assert_that(...)` instead",
                )
    return violations


def main() -> int:
    """Check for bare ``assert`` statements in a test tree.

    When invoked from ``validate.sh`` the root defaults to ``tests`` in
    the current working directory; an explicit root may be passed as
    the first argument.

    Returns:
        Process exit code: ``0`` when every assertion uses ``assertpy``,
        ``1`` when any bare ``assert`` is found or the root is missing.
    """
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests")
    if not root.is_dir():
        print(f"Directory not found: {root}", file=sys.stderr)
        return 1
    violations = find_bare_asserts(root=root)
    if violations:
        print("Bare `assert` statements found (use assertpy `assert_that`):")
        for violation in violations:
            print(violation)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
