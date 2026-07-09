"""Tests for ``scripts/audit_lgtm_ci_adoption.py``.

``gh api`` calls are mocked via ``monkeypatch``; local workflow files
are written to ``tmp_path``.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - only CompletedProcess is constructed
from pathlib import Path

import pytest

import audit_lgtm_ci_adoption as audit

SHA_A = "fc73b3ab8342a24597c12d137d6ff7fca84b9fe2"
SHA_B = "0" * 40


def _write_workflow(
    workflows_dir: Path,
    name: str,
    called: str,
    sha: str,
) -> None:
    """Write a minimal caller workflow file.

    Args:
        workflows_dir: Directory to write the workflow into.
        name: File name of the caller workflow.
        called: lgtm-ci workflow file name the caller uses.
        sha: SHA the call is pinned at.
    """
    workflows_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / name).write_text(
        f"jobs:\n  call:\n    uses: lgtm-hq/lgtm-ci/.github/workflows/{called}@{sha}\n",
        encoding="utf-8",
    )


def _fake_gh(
    names: list[str],
    returncode: int = 0,
    stderr: str = "",
) -> object:
    """Build a fake ``subprocess.run`` returning a contents listing.

    Args:
        names: File names to include in the fake API response.
        returncode: Exit code the fake ``gh`` call reports.
        stderr: Stderr text for the fake call.

    Returns:
        A callable usable as a ``subprocess.run`` replacement.
    """

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return subprocess.CompletedProcess(
            args=["gh"],
            returncode=returncode,
            stdout=json.dumps([{"name": name} for name in names]),
            stderr=stderr,
        )

    return run


def test_find_pins_collects_names_and_shas(tmp_path: Path) -> None:
    """Callers are mapped to the SHA they pin."""
    _write_workflow(tmp_path, "ci.yml", "reusable-quality.yml", SHA_A)
    _write_workflow(tmp_path, "tag.yml", "reusable-release-auto-tag.yml", SHA_A)
    pins = audit.find_lgtm_ci_pins(workflows_dir=tmp_path)
    assert pins == {
        "reusable-quality.yml": {SHA_A},
        "reusable-release-auto-tag.yml": {SHA_A},
    }


def test_find_pins_empty_dir(tmp_path: Path) -> None:
    """A directory without lgtm-ci callers yields no pins."""
    tmp_path.joinpath("other.yml").write_text(
        "jobs: {}\n",
        encoding="utf-8",
    )
    assert audit.find_lgtm_ci_pins(workflows_dir=tmp_path) == {}


def test_find_pins_preserves_duplicate_name_mixed_shas(tmp_path: Path) -> None:
    """Same workflow name at two SHAs keeps both refs for mixed detection."""
    _write_workflow(tmp_path, "ci.yml", "reusable-quality.yml", SHA_A)
    _write_workflow(tmp_path, "ci-old.yml", "reusable-quality.yml", SHA_B)
    pins = audit.find_lgtm_ci_pins(workflows_dir=tmp_path)
    assert pins == {"reusable-quality.yml": {SHA_A, SHA_B}}
    with pytest.raises(ValueError, match="mixed"):
        audit.resolve_pinned_ref(pins=pins)


def test_find_pins_reads_yaml_extension(tmp_path: Path) -> None:
    """Workflow files ending in .yaml are scanned like .yml."""
    _write_workflow(tmp_path, "ci.yaml", "reusable-quality.yml", SHA_A)
    pins = audit.find_lgtm_ci_pins(workflows_dir=tmp_path)
    assert pins == {"reusable-quality.yml": {SHA_A}}


def test_resolve_pinned_ref_single() -> None:
    """A single common SHA resolves cleanly."""
    ref = audit.resolve_pinned_ref(
        pins={"a.yml": {SHA_A}, "b.yml": {SHA_A}},
    )
    assert ref == SHA_A


def test_resolve_pinned_ref_rejects_empty_and_mixed() -> None:
    """No pins or mixed pins raise ValueError."""
    with pytest.raises(ValueError, match="no lgtm-ci"):
        audit.resolve_pinned_ref(pins={})
    with pytest.raises(ValueError, match="mixed"):
        audit.resolve_pinned_ref(
            pins={"a.yml": {SHA_A}, "b.yml": {SHA_B}},
        )


def test_list_available_filters_reusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only reusable-*.yml entries are returned, sorted."""
    monkeypatch.setattr(
        audit.subprocess,
        "run",
        _fake_gh(
            names=[
                "reusable-validate.yml",
                "ci.yml",
                "reusable-codeql.yml",
                "renovate.yml",
            ],
        ),
    )
    available = audit.list_available_workflows(ref=SHA_A)
    assert available == ["reusable-codeql.yml", "reusable-validate.yml"]


def test_list_available_gh_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing gh call raises RuntimeError."""
    monkeypatch.setattr(
        audit.subprocess,
        "run",
        _fake_gh(names=[], returncode=1, stderr="boom"),
    )
    with pytest.raises(RuntimeError, match="boom"):
        audit.list_available_workflows(ref=SHA_A)


def test_build_report_sections_and_counts() -> None:
    """Report splits adopted vs unadopted and counts both."""
    report = audit.build_report(
        available=["reusable-a.yml", "reusable-b.yml", "reusable-c.yml"],
        called={"reusable-b.yml"},
    )
    assert "Adopted (1):" in report
    assert "  reusable-b.yml" in report
    assert "Available, unadopted (2):" in report
    assert "1/3 available reusable workflows adopted" in report


def test_main_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() prints ref, adopted, and unadopted sections."""
    _write_workflow(tmp_path, "ci.yml", "reusable-quality.yml", SHA_A)
    monkeypatch.setattr(
        audit.subprocess,
        "run",
        _fake_gh(names=["reusable-quality.yml", "reusable-codeql.yml"]),
    )
    code = audit.main(argv=["--workflows-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert f"lgtm-ci pinned ref: {SHA_A}" in out
    assert "Adopted (1):" in out
    assert "Available, unadopted (1):" in out


def test_main_no_pins_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() exits 2 when no lgtm-ci callers exist."""
    code = audit.main(argv=["--workflows-dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert code == 2
    assert "no lgtm-ci" in err


def test_main_mixed_pins_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() exits non-zero when local callers pin mixed SHAs."""
    _write_workflow(tmp_path, "ci.yml", "reusable-quality.yml", SHA_A)
    _write_workflow(tmp_path, "ci-old.yml", "reusable-quality.yml", SHA_B)
    code = audit.main(argv=["--workflows-dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert code != 0
    assert "mixed" in err
