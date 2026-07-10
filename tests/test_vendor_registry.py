"""Tests for vendor registry validation and baked-index filtering."""

from __future__ import annotations

from pathlib import Path

import pytest
from assertpy import assert_that

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
