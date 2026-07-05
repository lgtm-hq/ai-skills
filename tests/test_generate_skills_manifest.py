"""Tests for ``scripts/generate_skills_manifest.py``."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from assertpy import assert_that


def _load_generate_skills_manifest_module() -> ModuleType:
    """Load ``generate_skills_manifest`` from the scripts directory.

    Returns:
        The loaded module object.

    Raises:
        RuntimeError: If the module spec or loader cannot be constructed.
    """
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "generate_skills_manifest.py"
    spec = importlib.util.spec_from_file_location(
        name="generate_skills_manifest",
        location=path,
    )
    if spec is None:
        msg = f"Could not load module spec from {path}"
        raise RuntimeError(msg)
    loader = spec.loader
    if loader is None:
        msg = f"Module spec for {path} has no loader"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def _write_skill(*, repo_root: Path, skill_id: str, body: str = "") -> Path:
    """Create a minimal skill directory for tests.

    Args:
        repo_root: Fake repository root.
        skill_id: Skill directory name under ``skills/``.
        body: Extra content appended after the frontmatter.

    Returns:
        Path of the written ``SKILL.md`` file.
    """
    skill_dir = repo_root / "skills" / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        f"---\nname: {skill_id}\ndescription: Test skill.\n---\n{body}",
        encoding="utf-8",
    )
    return skill_file


def test_compute_manifest_hashes_match_sha256_of_file_bytes(
    tmp_path: Path,
) -> None:
    """Each entry is the sha256 hex digest of the SKILL.md file bytes."""

    mod = _load_generate_skills_manifest_module()
    alpha = _write_skill(repo_root=tmp_path, skill_id="alpha", body="Alpha.\n")
    beta = _write_skill(repo_root=tmp_path, skill_id="beta", body="Beta.\n")

    manifest = mod._compute_manifest(repo_root=tmp_path)

    assert_that(manifest).is_equal_to(
        {
            "alpha": hashlib.sha256(alpha.read_bytes()).hexdigest(),
            "beta": hashlib.sha256(beta.read_bytes()).hexdigest(),
        }
    )


def test_compute_manifest_skips_non_skill_entries(tmp_path: Path) -> None:
    """Directories without SKILL.md and stray files are excluded."""

    mod = _load_generate_skills_manifest_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    (tmp_path / "skills" / "not-a-skill").mkdir()
    (tmp_path / "skills" / "README.md").write_text("stray\n", encoding="utf-8")

    manifest = mod._compute_manifest(repo_root=tmp_path)

    assert_that(sorted(manifest)).is_equal_to(["alpha"])


def test_compute_manifest_requires_skills_directory(tmp_path: Path) -> None:
    """A missing skills/ directory raises FileNotFoundError."""

    mod = _load_generate_skills_manifest_module()

    with pytest.raises(FileNotFoundError):
        mod._compute_manifest(repo_root=tmp_path)


def test_render_manifest_is_sorted_with_trailing_newline(
    tmp_path: Path,
) -> None:
    """Rendered JSON has sorted keys and ends with exactly one newline."""

    mod = _load_generate_skills_manifest_module()
    rendered = mod._render_manifest(manifest={"zeta": "00", "alpha": "11"})

    assert_that(rendered).ends_with("\n")
    assert_that(rendered.endswith("\n\n")).is_false()
    assert_that(list(json.loads(rendered))).is_equal_to(["alpha", "zeta"])


def test_generator_is_deterministic_across_runs(tmp_path: Path) -> None:
    """Two consecutive runs produce byte-identical manifest files."""

    mod = _load_generate_skills_manifest_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_skill(repo_root=tmp_path, skill_id="beta")
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    exit_first = mod.main(
        ["--repo-root", str(tmp_path), "--output", str(first)],
    )
    exit_second = mod.main(
        ["--repo-root", str(tmp_path), "--output", str(second)],
    )

    assert_that(exit_first).is_equal_to(0)
    assert_that(exit_second).is_equal_to(0)
    assert_that(first.read_bytes()).is_equal_to(second.read_bytes())


def test_check_passes_for_fresh_manifest(tmp_path: Path) -> None:
    """--check exits 0 when the manifest matches generated content."""

    mod = _load_generate_skills_manifest_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    manifest_path = tmp_path / "skills-manifest.json"

    assert_that(
        mod.main(
            ["--repo-root", str(tmp_path), "--output", str(manifest_path)],
        )
    ).is_equal_to(0)
    assert_that(
        mod.main(
            ["--repo-root", str(tmp_path), "--check", str(manifest_path)],
        )
    ).is_equal_to(0)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param("edit-skill", id="skill-content-drift"),
        pytest.param("edit-manifest", id="manifest-tampering"),
    ],
)
def test_check_fails_on_drift(
    tmp_path: Path,
    mutation: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--check exits 1 with a diff when manifest and skills diverge."""

    mod = _load_generate_skills_manifest_module()
    skill_file = _write_skill(repo_root=tmp_path, skill_id="alpha")
    manifest_path = tmp_path / "skills-manifest.json"
    assert_that(
        mod.main(
            ["--repo-root", str(tmp_path), "--output", str(manifest_path)],
        )
    ).is_equal_to(0)

    if mutation == "edit-skill":
        skill_file.write_text("---\nname: alpha\n---\nchanged\n", encoding="utf-8")
    else:
        manifest_path.write_text('{\n  "alpha": "bad"\n}\n', encoding="utf-8")

    exit_code = mod.main(
        ["--repo-root", str(tmp_path), "--check", str(manifest_path)],
    )

    assert_that(exit_code).is_equal_to(1)
    captured = capsys.readouterr()
    assert_that(captured.err).contains("Manifest is stale")
    assert_that(captured.err).contains("---")


def test_check_fails_when_manifest_missing(tmp_path: Path) -> None:
    """--check exits 1 when the manifest file does not exist."""

    mod = _load_generate_skills_manifest_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")

    exit_code = mod.main(
        ["--repo-root", str(tmp_path), "--check", str(tmp_path / "missing.json")],
    )

    assert_that(exit_code).is_equal_to(1)
