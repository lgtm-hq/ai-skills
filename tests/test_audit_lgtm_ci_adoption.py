"""Tests for ``scripts/audit_lgtm_ci_adoption.py``.

``gh api`` calls are mocked via ``monkeypatch``; local workflow files
are written to ``tmp_path``.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - only CompletedProcess is constructed
from pathlib import Path

import audit_lgtm_ci_adoption as audit
import pytest
from assertpy import assert_that

SHA_A = "fc73b3ab8342a24597c12d137d6ff7fca84b9fe2"
SHA_B = "0" * 40


def _write_workflow(
    workflows_dir: Path,
    name: str,
    called: str,
    sha: str,
    tooling_ref: str | None = None,
    tooling_ref_quote: str = '"',
) -> None:
    """Write a minimal caller workflow file.

    Args:
        workflows_dir: Directory to write the workflow into.
        name: File name of the caller workflow.
        called: lgtm-ci workflow file name the caller uses.
        sha: SHA the call is pinned at.
        tooling_ref: Optional ``tooling-ref`` SHA. When omitted the
            caller has no tooling-ref key.
        tooling_ref_quote: Quote character written around
            ``tooling-ref``. Production callers use both ``"`` and
            ``'`` (see ``codeql.yml``).
    """
    workflows_dir.mkdir(parents=True, exist_ok=True)
    body = (
        f"jobs:\n  call:\n    uses: lgtm-hq/lgtm-ci/.github/workflows/{called}@{sha}\n"
    )
    if tooling_ref is not None:
        quoted = f"{tooling_ref_quote}{tooling_ref}{tooling_ref_quote}"
        body += f"    with:\n      tooling-ref: {quoted}\n"
    (workflows_dir / name).write_text(body, encoding="utf-8")


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


def _fake_gh_by_ref(
    names_by_ref: dict[str, list[str]],
    returncode: int = 0,
    stderr: str = "",
) -> object:
    """Build a fake ``gh api`` that returns different listings per ref.

    Args:
        names_by_ref: Mapping of git SHA to reusable workflow file names
            available at that ref.
        returncode: Exit code the fake ``gh`` call reports.
        stderr: Stderr text for the fake call.

    Returns:
        A callable usable as a ``subprocess.run`` replacement.
    """

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        argv = args[0] if args else []
        url = argv[2] if isinstance(argv, list) and len(argv) > 2 else ""
        ref = str(url).rsplit("ref=", maxsplit=1)[-1]
        names = names_by_ref.get(ref, [])
        return subprocess.CompletedProcess(
            args=["gh"],
            returncode=returncode,
            stdout=json.dumps([{"name": name} for name in names]),
            stderr=stderr,
        )

    return run


def test_find_pins_collects_names_and_shas(tmp_path: Path) -> None:
    """Callers are mapped to the SHA they pin."""
    _write_workflow(
        workflows_dir=tmp_path,
        name="ci.yml",
        called="reusable-quality.yml",
        sha=SHA_A,
    )
    _write_workflow(
        workflows_dir=tmp_path,
        name="tag.yml",
        called="reusable-release-auto-tag.yml",
        sha=SHA_A,
    )
    pins = audit.find_lgtm_ci_pins(workflows_dir=tmp_path)
    assert_that(pins).is_equal_to(
        {
            "reusable-quality.yml": {SHA_A},
            "reusable-release-auto-tag.yml": {SHA_A},
        },
    )


def test_find_pins_empty_dir(tmp_path: Path) -> None:
    """A directory without lgtm-ci callers yields no pins."""
    tmp_path.joinpath("other.yml").write_text(
        "jobs: {}\n",
        encoding="utf-8",
    )
    assert_that(audit.find_lgtm_ci_pins(workflows_dir=tmp_path)).is_equal_to({})


def test_find_pins_preserves_duplicate_name_mixed_shas(tmp_path: Path) -> None:
    """Same workflow name at two SHAs keeps both refs for mixed detection."""
    _write_workflow(
        workflows_dir=tmp_path,
        name="ci.yml",
        called="reusable-quality.yml",
        sha=SHA_A,
    )
    _write_workflow(
        workflows_dir=tmp_path,
        name="ci-old.yml",
        called="reusable-quality.yml",
        sha=SHA_B,
    )
    pins = audit.find_lgtm_ci_pins(workflows_dir=tmp_path)
    assert_that(pins).is_equal_to({"reusable-quality.yml": {SHA_A, SHA_B}})
    with pytest.raises(ValueError, match="mixed"):
        audit.resolve_pinned_ref(pins=pins)


def test_find_pins_reads_yaml_extension(tmp_path: Path) -> None:
    """Workflow files ending in .yaml are scanned like .yml."""
    _write_workflow(
        workflows_dir=tmp_path,
        name="ci.yaml",
        called="reusable-quality.yml",
        sha=SHA_A,
    )
    pins = audit.find_lgtm_ci_pins(workflows_dir=tmp_path)
    assert_that(pins).is_equal_to({"reusable-quality.yml": {SHA_A}})


def test_resolve_pinned_ref_single() -> None:
    """A single common SHA resolves cleanly."""
    ref = audit.resolve_pinned_ref(
        pins={"a.yml": {SHA_A}, "b.yml": {SHA_A}},
    )
    assert_that(ref).is_equal_to(SHA_A)


def test_resolve_pinned_ref_rejects_empty_and_mixed() -> None:
    """No pins or mixed pins raise ValueError."""
    with pytest.raises(ValueError, match="no lgtm-ci"):
        audit.resolve_pinned_ref(pins={})
    with pytest.raises(ValueError, match="mixed"):
        audit.resolve_pinned_ref(
            pins={"a.yml": {SHA_A}, "b.yml": {SHA_B}},
        )


def test_resolve_pinned_ref_excludes_ai_review() -> None:
    """A newer reusable-ai-review pin does not fail repo-wide uniqueness."""
    ref = audit.resolve_pinned_ref(
        pins={
            "reusable-quality.yml": {SHA_A},
            audit.AI_REVIEW_WORKFLOW: {SHA_B},
        },
        exclude=frozenset({audit.AI_REVIEW_WORKFLOW}),
    )
    assert_that(ref).is_equal_to(SHA_A)


def test_resolve_pinned_ref_falls_back_to_sole_ai_review() -> None:
    """An ai-review-only tree still resolves instead of reporting no pins."""
    ref = audit.resolve_pinned_ref(
        pins={audit.AI_REVIEW_WORKFLOW: {SHA_B}},
        exclude=frozenset({audit.AI_REVIEW_WORKFLOW}),
    )
    assert_that(ref).is_equal_to(SHA_B)


def test_assert_single_pin_per_name_rejects_internal_mix() -> None:
    """Two SHAs for one reusable name fail even when excluded repo-wide."""
    with pytest.raises(ValueError, match="inside"):
        audit.assert_single_pin_per_name(
            pins={audit.AI_REVIEW_WORKFLOW: {SHA_A, SHA_B}},
            name=audit.AI_REVIEW_WORKFLOW,
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
    assert_that(available).is_equal_to(
        ["reusable-codeql.yml", "reusable-validate.yml"],
    )


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
    assert_that(report).contains("Adopted (1):")
    assert_that(report).contains("  reusable-b.yml")
    assert_that(report).contains("Available, unadopted (2):")
    assert_that(report).contains("1/3 available reusable workflows adopted")


def test_main_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() prints ref, adopted, and unadopted sections."""
    _write_workflow(
        workflows_dir=tmp_path,
        name="ci.yml",
        called="reusable-quality.yml",
        sha=SHA_A,
    )
    monkeypatch.setattr(
        audit.subprocess,
        "run",
        _fake_gh(names=["reusable-quality.yml", "reusable-codeql.yml"]),
    )
    code = audit.main(argv=["--workflows-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert_that(code).is_equal_to(0)
    assert_that(out).contains(f"lgtm-ci pinned ref: {SHA_A}")
    assert_that(out).contains("Adopted (1):")
    assert_that(out).contains("Available, unadopted (1):")


def test_main_no_pins_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() exits 2 when no lgtm-ci callers exist."""
    code = audit.main(argv=["--workflows-dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert_that(code).is_equal_to(2)
    assert_that(err).contains("no lgtm-ci")


def test_main_mixed_pins_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() exits non-zero when local callers pin mixed SHAs."""
    _write_workflow(
        workflows_dir=tmp_path,
        name="ci.yml",
        called="reusable-quality.yml",
        sha=SHA_A,
    )
    _write_workflow(
        workflows_dir=tmp_path,
        name="ci-old.yml",
        called="reusable-quality.yml",
        sha=SHA_B,
    )
    code = audit.main(argv=["--workflows-dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert_that(code).is_not_equal_to(0)
    assert_that(err).contains("mixed")


def test_main_allows_newer_ai_review_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() treats a newer reusable-ai-review SHA as adopted, not mixed."""
    _write_workflow(
        workflows_dir=tmp_path,
        name="ci.yml",
        called="reusable-quality.yml",
        sha=SHA_A,
        tooling_ref=SHA_A,
    )
    _write_workflow(
        workflows_dir=tmp_path,
        name="ai-review.yml",
        called=audit.AI_REVIEW_WORKFLOW,
        sha=SHA_B,
        tooling_ref=SHA_B,
    )
    monkeypatch.setattr(
        audit.subprocess,
        "run",
        _fake_gh_by_ref(
            names_by_ref={
                SHA_A: ["reusable-quality.yml"],
                SHA_B: [audit.AI_REVIEW_WORKFLOW],
            },
        ),
    )
    code = audit.main(argv=["--workflows-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert_that(code).is_equal_to(0)
    assert_that(out).contains(f"lgtm-ci pinned ref: {SHA_A}")
    assert_that(out).contains(f"{audit.AI_REVIEW_WORKFLOW} pinned ref: {SHA_B}")
    assert_that(out).contains(f"  {audit.AI_REVIEW_WORKFLOW}")
    assert_that(out).contains("Adopted (2):")


def test_main_sole_ai_review_caller_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """main() reports adoption when reusable-ai-review.yml is the only caller."""
    _write_workflow(
        workflows_dir=tmp_path,
        name="ai-review.yml",
        called=audit.AI_REVIEW_WORKFLOW,
        sha=SHA_B,
    )
    monkeypatch.setattr(
        audit.subprocess,
        "run",
        _fake_gh(names=[audit.AI_REVIEW_WORKFLOW, "reusable-quality.yml"]),
    )
    code = audit.main(argv=["--workflows-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert_that(code).is_equal_to(0)
    assert_that(out).contains(f"lgtm-ci pinned ref: {SHA_B}")
    assert_that(out).contains("Adopted (1):")
    assert_that(out).contains(f"  {audit.AI_REVIEW_WORKFLOW}")


def test_main_rejects_mixed_pins_inside_ai_review(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two reusable-ai-review SHAs fail even when other callers agree."""
    _write_workflow(
        workflows_dir=tmp_path,
        name="ci.yml",
        called="reusable-quality.yml",
        sha=SHA_A,
    )
    _write_workflow(
        workflows_dir=tmp_path,
        name="ai-review.yml",
        called=audit.AI_REVIEW_WORKFLOW,
        sha=SHA_A,
    )
    _write_workflow(
        workflows_dir=tmp_path,
        name="ai-review-old.yml",
        called=audit.AI_REVIEW_WORKFLOW,
        sha=SHA_B,
    )
    code = audit.main(argv=["--workflows-dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert_that(code).is_equal_to(2)
    assert_that(err).contains("inside")


def test_main_rejects_uses_tooling_ref_mismatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Matching uses SHAs still fail when tooling-ref drifts."""
    _write_workflow(
        workflows_dir=tmp_path,
        name="ci.yml",
        called="reusable-quality.yml",
        sha=SHA_A,
        tooling_ref=SHA_A,
    )
    _write_workflow(
        workflows_dir=tmp_path,
        name="ai-review.yml",
        called=audit.AI_REVIEW_WORKFLOW,
        sha=SHA_B,
        tooling_ref=SHA_A,
    )
    code = audit.main(argv=["--workflows-dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert_that(code).is_equal_to(2)
    assert_that(err).contains("tooling-ref")


def test_assert_uses_tooling_ref_lockstep_accepts_match(
    tmp_path: Path,
) -> None:
    """uses and tooling-ref on the same SHA pass."""
    _write_workflow(
        workflows_dir=tmp_path,
        name="ai-review.yml",
        called=audit.AI_REVIEW_WORKFLOW,
        sha=SHA_B,
        tooling_ref=SHA_B,
    )
    audit.assert_uses_tooling_ref_lockstep(workflows_dir=tmp_path)


def test_assert_uses_tooling_ref_lockstep_accepts_single_quoted_match(
    tmp_path: Path,
) -> None:
    """Single-quoted tooling-ref is parsed like codeql.yml."""
    _write_workflow(
        workflows_dir=tmp_path,
        name="codeql.yml",
        called="reusable-codeql.yml",
        sha=SHA_A,
        tooling_ref=SHA_A,
        tooling_ref_quote="'",
    )
    audit.assert_uses_tooling_ref_lockstep(workflows_dir=tmp_path)


def test_assert_uses_tooling_ref_lockstep_rejects_single_quoted_mismatch(
    tmp_path: Path,
) -> None:
    """Single-quoted tooling-ref still fails when it drifts from uses."""
    _write_workflow(
        workflows_dir=tmp_path,
        name="codeql.yml",
        called="reusable-codeql.yml",
        sha=SHA_A,
        tooling_ref=SHA_B,
        tooling_ref_quote="'",
    )
    with pytest.raises(ValueError, match="tooling-ref"):
        audit.assert_uses_tooling_ref_lockstep(workflows_dir=tmp_path)


def test_production_workflows_uses_tooling_ref_lockstep() -> None:
    """Committed callers keep uses and tooling-ref on the same SHA."""
    workflows_dir = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    pins = audit.find_lgtm_ci_pins(workflows_dir=workflows_dir)
    assert_that(pins).contains_key(audit.AI_REVIEW_WORKFLOW)
    audit.assert_uses_tooling_ref_lockstep(workflows_dir=workflows_dir)
