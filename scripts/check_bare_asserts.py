#!/usr/bin/env python3
"""Check that test modules use assertpy instead of bare ``assert``.

Enforces the owner standard (#88): every assertion in ``tests/`` must
go through :func:`assertpy.assert_that`, never a bare ``assert``
statement. Earlier revisions scanned line text with ``grep``, which
flagged the word ``assert`` wherever it appeared -- including inside
docstrings and comments (for example prose describing an assertion).

This checker parses each test module with :func:`ast.parse` and walks
the tree for :class:`ast.Assert` nodes, so only real ``assert``
statements are reported. Both the ``assert expr`` and ``assert(expr)``
forms parse to the same node type and are caught; text inside strings,
docstrings, and comments is inherently ignored.

Prints one line per violation (``path:line: message``) and exits 1 on
any violation, keeping the output CI-greppable.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

DEFAULT_ROOT = Path("tests")


def find_bare_asserts(
    root: Path,
) -> list[str]:
    """Find bare ``assert`` statements under a test tree.

    Args:
        root: Directory tree to scan for ``*.py`` files.

    Returns:
        A list of violation messages (``path:line: ...``); empty when
        no module contains a bare ``assert`` statement.
    """
    violations: list[str] = []
    for py_file in sorted(root.rglob("*.py")):
        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append(f"{py_file}:0: cannot read file: {exc}")
            continue
        try:
            tree = ast.parse(source=source, filename=str(py_file))
        except SyntaxError as exc:
            violations.append(
                f"{py_file}:{exc.lineno or 0}: cannot parse file: {exc.msg}",
            )
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                violations.append(
                    f"{py_file}:{node.lineno}: bare assert statement "
                    f"(use assertpy assert_that)",
                )
    return violations


def main() -> int:
    """Check for bare ``assert`` statements in a test tree.

    When invoked from ``validate.sh`` the root defaults to ``tests``;
    an explicit root may be passed as the first argument.

    Returns:
        Process exit code: ``0`` when no bare ``assert`` is found,
        ``1`` when any violation is found or the root is missing.
    """
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ROOT
    if not root.is_dir():
        print(f"Directory not found: {root}", file=sys.stderr)
        return 1
    violations = find_bare_asserts(root=root)
    if violations:
        print("Bare-assert check found violations (see each line for details):")
        for violation in violations:
            print(violation)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
