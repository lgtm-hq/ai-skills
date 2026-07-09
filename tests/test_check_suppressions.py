"""Tests for the suppression-justification checker.

Marker strings are assembled from parts so this file never contains a
literal suppression marker that the checker (or a repo-wide grep) would
flag.
"""

from __future__ import annotations

from pathlib import Path

from check_suppressions import find_unjustified_suppressions
from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]

NOQA = "# " + "no" + "qa"
NOSEC = "# " + "no" + "sec"
NOSEMGREP = "# " + "no" + "semgrep"
TYPE_IGNORE = "# " + "type: " + "ignore"


def _write_module(
    tmp_path: Path,
    line: str,
) -> Path:
    """Write a one-line Python module into a temp tree.

    Args:
        tmp_path: Pytest temporary directory acting as fake repo root.
        line: Source line to write into ``module.py``.

    Returns:
        The temp tree root to scan.
    """
    (tmp_path / "module.py").write_text(f"{line}\n", encoding="utf-8")
    logger.debug("Wrote module.py with line: {}", line)
    return tmp_path


def test_unjustified_marker_is_flagged(
    tmp_path: Path,
) -> None:
    """Flag each bare suppression marker that lacks a reason suffix."""
    for index, marker in enumerate([NOQA, NOSEC, NOSEMGREP, TYPE_IGNORE]):
        case_root = tmp_path / f"case-{index}"
        case_root.mkdir()
        root = _write_module(tmp_path=case_root, line=f"x = call()  {marker}")

        violations = find_unjustified_suppressions(root=root)

        assert len(violations) == 1, marker
        assert "module.py:1" in violations[0]
        logger.info("[TEST] bare marker flagged: {}", violations[0])


def test_specific_code_without_reason_is_flagged(
    tmp_path: Path,
) -> None:
    """Flag a rule-scoped suppression that still lacks a reason."""
    root = _write_module(tmp_path=tmp_path, line=f"x = call()  {NOSEC} B603")

    violations = find_unjustified_suppressions(root=root)

    assert len(violations) == 1
    logger.info("[TEST] code without reason flagged: {}", violations[0])


def test_justified_suppression_passes(
    tmp_path: Path,
) -> None:
    """Accept suppressions that carry an inline '- reason' justification."""
    lines = [
        f"x = call()  {NOSEC} B603 - fixed argv list, no shell",
        f"x = call()  {NOQA}: S603 {NOSEC} B603 B607 - fixed gh argv",
        f"y = z  {TYPE_IGNORE}[arg-type] - upstream stub is wrong",
        f"{NOSEMGREP} - URL template pins scheme and host",
    ]
    for index, line in enumerate(lines):
        case_root = tmp_path / f"case-{index}"
        case_root.mkdir()
        root = _write_module(tmp_path=case_root, line=line)

        violations = find_unjustified_suppressions(root=root)

        assert violations == [], line
        logger.info("[TEST] justified suppression accepted: {}", line)


def test_dash_before_marker_does_not_count_as_reason(
    tmp_path: Path,
) -> None:
    """Reject a line whose only ' - ' appears before the marker."""
    root = _write_module(tmp_path=tmp_path, line=f"x = a - b  {NOQA}: E501")

    violations = find_unjustified_suppressions(root=root)

    assert len(violations) == 1
    logger.info("[TEST] pre-marker dash rejected: {}", violations[0])


def test_reason_before_later_marker_is_flagged(
    tmp_path: Path,
) -> None:
    """Reject a justified marker followed by a bare later suppression."""
    root = _write_module(
        tmp_path=tmp_path,
        line=f"x = call()  {NOSEC} B603 - fixed argv  {NOQA}: E501",
    )

    violations = find_unjustified_suppressions(root=root)

    assert len(violations) == 1
    logger.info(
        "[TEST] later bare marker flagged: {}",
        violations[0],
    )


def test_lines_without_markers_pass(
    tmp_path: Path,
) -> None:
    """Ignore ordinary code and comments without suppression markers."""
    root = _write_module(tmp_path=tmp_path, line="x = 1  # plain comment")

    violations = find_unjustified_suppressions(root=root)

    assert violations == []
    logger.info("[TEST] plain code passes")


def test_skip_dirs_are_not_scanned(
    tmp_path: Path,
) -> None:
    """Skip vendored and generated directories entirely."""
    vendored = tmp_path / ".venv" / "lib"
    vendored.mkdir(parents=True)
    (vendored / "bad.py").write_text(f"x = call()  {NOSEC}\n", encoding="utf-8")

    violations = find_unjustified_suppressions(root=tmp_path)

    assert violations == []
    logger.info("[TEST] skip dirs excluded from scan")


def test_current_repository_tree_passes() -> None:
    """The real repository must satisfy its own suppression policy."""
    violations = find_unjustified_suppressions(root=REPO_ROOT)

    assert violations == []
    logger.info("[TEST] repository tree clean of unjustified suppressions")
