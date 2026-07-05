#!/usr/bin/env python3
"""Check that lint-suppression comments carry an inline justification.

Enforces the `lint` skill ignore policy: every suppression marker
(``noqa``, ``nosec``, ``nosemgrep``, ``type: ignore``) in repository
Python files must be followed by a ``- reason`` comment on the same
line, e.g.::

    subprocess.run(["validate.sh"])  # nosec B603 - fixed argv list

The heuristic is cheap by design: after the first marker on a line
there must be ``- <text>`` (a dash surrounded by whitespace, then a
reason). One trailing reason covers multiple markers on the same line.

Prints one line per violation (including the file path and line
number) and exits 1 on any violation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Assembled from parts so this file never contains a literal marker
# that would flag itself.
_MARKER_NAMES = ("no" + "qa", "no" + "sec", "no" + "semgrep", r"type:\s*ignore")
MARKER_PATTERN = re.compile(rf"#\s*(?:{'|'.join(_MARKER_NAMES)})\b")
REASON_PATTERN = re.compile(r"\s-\s+\S")
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


def find_unjustified_suppressions(
    root: Path,
) -> list[str]:
    """Find suppression markers lacking a justification under a root.

    Args:
        root: Directory tree to scan for ``*.py`` files.

    Returns:
        A list of violation messages (``path:line: ...``); empty when
        every suppression carries a ``- reason`` suffix.
    """
    violations: list[str] = []
    for py_file in sorted(root.rglob("*.py")):
        relative = py_file.relative_to(root)
        if _is_skipped(relative=relative):
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append(f"{relative}: cannot read file: {exc}")
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = MARKER_PATTERN.search(line)
            if match is None:
                continue
            if REASON_PATTERN.search(line, match.end()) is None:
                violations.append(
                    f"{relative}:{line_number}: suppression without inline "
                    f"'- reason' justification: {line.strip()}",
                )
    return violations


def main() -> int:
    """Check suppression justifications for a repository tree.

    When invoked from ``validate.sh``, the root defaults to the current
    working directory; an explicit root may be passed as the first
    argument.

    Returns:
        Process exit code: ``0`` when every suppression is justified,
        ``1`` when any violation is found or the root is missing.
    """
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path()
    if not root.is_dir():
        print(f"Directory not found: {root}", file=sys.stderr)
        return 1
    violations = find_unjustified_suppressions(root=root)
    for violation in violations:
        print(violation)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
