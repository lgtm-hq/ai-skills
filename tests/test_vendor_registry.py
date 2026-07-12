"""Tests for vendor registry validation and baked-index filtering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from assertpy import assert_that

import bake_vendor_indexes
from vendor_registry.registry import (
    discover_skills,
    load_registry,
    render_index,
    render_notice,
    validate_index,
)
from vendor_registry.vendor import Vendor

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "vendor_registry"


@pytest.fixture
def valid_registry_path(tmp_path: Path) -> Path:
    """Copy the valid registry fixture into an isolated repository root.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        Path to the copied ``vendors.yaml`` fixture.
    """
    registry_path = tmp_path / "vendors.yaml"
    registry_path.write_text(
        FIXTURES_DIR.joinpath("valid-vendors.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return registry_path


def test_load_registry_accepts_valid_vendor(
    valid_registry_path: Path,
) -> None:
    """Accept a complete registry with forward-compatible glob roots."""
    vendors = load_registry(registry_path=valid_registry_path)

    assert_that(vendors).is_length(1)
    assert_that(vendors[0]).is_equal_to(
        Vendor(
            id="example-vendor",
            repo="owner/repository",
            sha="0123456789abcdef0123456789abcdef01234567",
            skill_roots=("plugins/*/skills", "skills"),
            license="MIT",
            homepage="https://example.com/repository",
        ),
    )


@pytest.mark.parametrize(
    ("source", "replacement", "message"),
    [
        pytest.param(
            "- id: example-vendor",
            "- id: Example",
            "id must be a lowercase slug",
            id="invalid-id",
        ),
        pytest.param(
            'sha: "0123456789abcdef0123456789abcdef01234567"',
            'sha: "short"',
            "sha must be a 40-character",
            id="invalid-sha",
        ),
        pytest.param(
            "skillRoots:\n      - plugins/*/skills\n      - skills",
            "skillRoots: []",
            "skillRoots must be a non-empty list",
            id="empty-roots",
        ),
        pytest.param(
            "skillRoots:\n      - plugins/*/skills\n      - skills",
            "skillRoots:\n      - /skills",
            "skillRoots entries must be relative",
            id="absolute-root",
        ),
        pytest.param(
            "homepage: https://example.com/repository",
            "homepage: ftp://example.com",
            r"homepage must be an http\(s\) URL",
            id="invalid-homepage",
        ),
    ],
)
def test_load_registry_rejects_invalid_required_fields(
    valid_registry_path: Path,
    source: str,
    replacement: str,
    message: str,
) -> None:
    """Fail closed when an individual vendor field violates schema."""
    registry_path = valid_registry_path
    contents = registry_path.read_text(encoding="utf-8")
    registry_path.write_text(
        contents.replace(source, replacement),
        encoding="utf-8",
    )

    with pytest.raises((TypeError, ValueError), match=message):
        load_registry(registry_path=registry_path)


def test_load_registry_accepts_optional_display_ref(
    valid_registry_path: Path,
) -> None:
    """Allow consumer-facing displayRef pins that are not commit SHAs."""
    registry_path = valid_registry_path
    contents = registry_path.read_text(encoding="utf-8")
    registry_path.write_text(
        contents.replace(
            "homepage: https://example.com/repository",
            "displayRef: latest\n    homepage: https://example.com/repository",
        ),
        encoding="utf-8",
    )

    vendors = load_registry(registry_path=registry_path)

    assert_that(vendors).is_length(1)
    assert_that(vendors[0].id).is_equal_to("example-vendor")


def test_load_registry_rejects_sha_display_ref(
    valid_registry_path: Path,
) -> None:
    """Reject displayRef values that look like commit SHAs."""
    registry_path = valid_registry_path
    contents = registry_path.read_text(encoding="utf-8")
    registry_path.write_text(
        contents.replace(
            "homepage: https://example.com/repository",
            "displayRef: 0123456789abcdef0123456789abcdef01234567\n"
            "    homepage: https://example.com/repository",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="displayRef must not be a commit SHA"):
        load_registry(registry_path=registry_path)


def test_load_registry_rejects_uppercase_sha_display_ref(
    valid_registry_path: Path,
) -> None:
    """Reject uppercase 40-char hex displayRef values as commit SHAs."""
    registry_path = valid_registry_path
    contents = registry_path.read_text(encoding="utf-8")
    registry_path.write_text(
        contents.replace(
            "homepage: https://example.com/repository",
            "displayRef: ABCDEF0123456789ABCDEF0123456789ABCDEF01\n"
            "    homepage: https://example.com/repository",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="displayRef must not be a commit SHA"):
        load_registry(registry_path=registry_path)


def test_discover_skills_filters_descendants_of_glob_roots() -> None:
    """Include all skill files below configured roots, including nested ones."""
    skills = discover_skills(
        paths=[
            "plugins/one/skills/alpha/SKILL.md",
            "plugins/two/skills/beta/SKILL.md",
            "plugins/one/skills/alpha/examples/SKILL.md",
            "plugins/one/other/gamma/SKILL.md",
            "skills/root/SKILL.md",
        ],
        skill_roots=("plugins/*/skills", "skills"),
    )

    assert_that(skills).is_equal_to(
        [
            {"name": "alpha", "path": "plugins/one/skills/alpha"},
            {
                "name": "examples",
                "path": "plugins/one/skills/alpha/examples",
            },
            {"name": "beta", "path": "plugins/two/skills/beta"},
            {"name": "root", "path": "skills/root"},
        ],
    )


def test_discover_skills_rejects_cross_directory_glob_matches() -> None:
    """Exclude paths where a root wildcard would otherwise cross directories."""
    skills = discover_skills(
        paths=[
            "plugins/one/extra/skills/alpha/SKILL.md",
            "plugins/one/skills/alpha/SKILL.md",
        ],
        skill_roots=("plugins/*/skills",),
    )

    assert_that(skills).is_equal_to(
        [{"name": "alpha", "path": "plugins/one/skills/alpha"}],
    )


def test_validate_index_accepts_matching_metadata_and_skills(tmp_path: Path) -> None:
    """Accept a stable index that matches its registry vendor offline."""
    vendor = Vendor(
        id="example",
        repo="owner/repository",
        sha="0123456789abcdef0123456789abcdef01234567",
        skill_roots=("skills",),
        license="MIT",
        homepage="https://example.com/repository",
    )
    index_path = tmp_path / "example.json"
    index_path.write_text(
        render_index(
            vendor=vendor,
            skills=[{"name": "alpha", "path": "skills/alpha"}],
        ),
        encoding="utf-8",
    )

    validate_index(index_path=index_path, vendor=vendor)


def test_validate_index_rejects_metadata_drift(tmp_path: Path) -> None:
    """Reject an index baked from a SHA other than the registry pin."""
    vendor = Vendor(
        id="example",
        repo="owner/repository",
        sha="0123456789abcdef0123456789abcdef01234567",
        skill_roots=("skills",),
        license="MIT",
        homepage="https://example.com/repository",
    )
    index_path = tmp_path / "example.json"
    index_path.write_text(
        """{
  "vendor": {
    "id": "example",
    "repo": "owner/repository",
    "sha": "ffffffffffffffffffffffffffffffffffffffff",
    "skillRoots": ["skills"]
  },
  "skills": []
}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="metadata does not match"):
        validate_index(index_path=index_path, vendor=vendor)


def test_render_notice_records_anthropic_document_skill_nuance() -> None:
    """Document the confirmed Anthropic registry license qualification."""
    notice = render_notice(
        vendors=(
            Vendor(
                id="anthropics",
                repo="anthropics/skills",
                sha="0123456789abcdef0123456789abcdef01234567",
                skill_roots=("skills",),
                license="Apache-2.0",
                homepage="https://github.com/anthropics/skills",
            ),
        ),
    )

    assert_that(notice).contains("document skills are source-available")
    assert_that(notice).contains("Apache-2.0")


def test_render_notice_records_claude_code_commercial_terms() -> None:
    """Document Claude Code plugin skills under Anthropic commercial terms."""
    notice = render_notice(
        vendors=(
            Vendor(
                id="anthropics-claude-code",
                repo="anthropics/claude-code",
                sha="0123456789abcdef0123456789abcdef01234567",
                skill_roots=("plugins/*/skills",),
                license="Commercial",
                homepage="https://github.com/anthropics/claude-code",
            ),
        ),
    )

    assert_that(notice).contains("anthropics/claude-code")
    assert_that(notice).contains("Commercial")
    assert_that(notice).contains("Commercial Terms of Service")


def test_committed_claude_code_index_includes_frontend_design() -> None:
    """Baked claude-code indexes must expose plugin-buried frontend-design."""
    repo_root = Path(__file__).resolve().parents[1]
    index_paths = (
        repo_root / "vendor-indexes" / "anthropics-claude-code.json",
        repo_root
        / "npm"
        / "ai-skills"
        / "data"
        / "vendor-indexes"
        / "anthropics-claude-code.json",
    )
    for index_path in index_paths:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        skills = {skill["name"]: skill["path"] for skill in payload["skills"]}

        assert_that(payload["vendor"]["id"]).is_equal_to("anthropics-claude-code")
        assert_that(payload["vendor"]["skillRoots"]).is_equal_to(
            ["plugins/*/skills"],
        )
        assert_that(skills).contains_key("frontend-design")
        assert_that(skills["frontend-design"]).is_equal_to(
            "plugins/frontend-design/skills/frontend-design",
        )
    root_index = index_paths[0].read_text(encoding="utf-8")
    packaged_index = index_paths[1].read_text(encoding="utf-8")
    assert_that(packaged_index).is_equal_to(root_index)


def test_bake_preserves_committed_artifacts_when_fetch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not replace committed output when a later vendor fetch fails."""
    tmp_path.joinpath("vendors.yaml").write_text(
        """---
vendors:
  - id: first
    repo: owner/first
    sha: "0123456789abcdef0123456789abcdef01234567"
    skillRoots: ["skills"]
    license: MIT
    homepage: https://example.com/first
  - id: second
    repo: owner/second
    sha: "89abcdef0123456789abcdef0123456789abcdef"
    skillRoots: ["skills"]
    license: MIT
    homepage: https://example.com/second
""",
        encoding="utf-8",
    )
    indexes_dir = tmp_path / "vendor-indexes"
    indexes_dir.mkdir()
    first_index = indexes_dir / "first.json"
    first_index.write_text("existing index\n", encoding="utf-8")
    notice_path = tmp_path / "NOTICE.md"
    notice_path.write_text("existing notice\n", encoding="utf-8")

    def _fetch_then_fail(*, vendor: Vendor) -> list[str]:
        """Return a first tree then simulate a later network failure.

        Args:
            vendor: Vendor being fetched.

        Returns:
            Blob paths for the first vendor.

        Raises:
            RuntimeError: For the second vendor's simulated API failure.
        """
        if vendor.id == "first":
            return ["skills/alpha/SKILL.md"]
        msg = "network failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(bake_vendor_indexes, "_fetch_tree_paths", _fetch_then_fail)

    with pytest.raises(RuntimeError, match="network failure"):
        bake_vendor_indexes.bake(repo_root=tmp_path)

    assert_that(first_index.read_text(encoding="utf-8")).is_equal_to("existing index\n")
    assert_that(notice_path.read_text(encoding="utf-8")).is_equal_to(
        "existing notice\n"
    )
