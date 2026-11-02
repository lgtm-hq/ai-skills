"""Legacy management replacements remove owned fields and retain manifest metadata."""

import copy
from collections.abc import Callable
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.legacy import legacy_documents, write_legacy
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.pins import write_vendors
from ai_skills_engine.vendors import manage

pytest_plugins = ("manifest_helpers",)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def author(tmp_path: Path) -> Path:
    """Seed real mappings plus manifest-only metadata, without fetching vendors.

    Args:
        tmp_path: Isolated repository.

    Returns:
        Manifest author root.
    """
    data = read_document(ROOT / "ai-skills.yaml")
    vendor = data["vendors"][0]
    vendor["x-vendor-note"] = "preserve"
    vendor["mapping"]["x-mapping-note"] = {"preserve": True}
    package = vendor["mapping"]["packages"][0]
    package.update(
        extraFiles=["NOTICE.md"],
        renameSkills={"teach": "teach-mapped"},
        agents=["reviewer"],
        capabilities={"teach": {"id": "stable"}},
        **{"x-package-note": "preserve"},
    )
    (tmp_path / "ai-skills.yaml").write_text(dump_document(data))
    write_legacy(tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    "field", ["extraFiles", "renameSkills", "agents", "plugins", "retained"]
)
def test_replacement_removes_only_omitted_legacy_owned_fields(
    author: Path, field: str
) -> None:
    """The production writer applies omission while preserving matching declarations."""
    path = author / "ai-skills.yaml"
    before = read_document(path)
    raw = copy.deepcopy(legacy_documents(before)["vendors.yaml"]["vendors"])
    if field == "plugins":
        raw[0].pop("plugins")
        # Removing publications requires the author to remove their exports too.
        before["exports"] = [
            value
            for value in before["exports"]
            if not value.startswith(f"{raw[0]['id']}/")
        ]
        path.write_text(dump_document(before))
    elif field != "retained":
        raw[0]["plugins"][0].pop(field)
    write_vendors(path, raw)
    after = read_document(path)
    mapping = after["vendors"][0]["mapping"]
    assert_that(mapping["x-mapping-note"]).is_equal_to({"preserve": True})
    assert_that(after["vendors"][0]["x-vendor-note"]).is_equal_to("preserve")
    assert_that(after["vendors"][1:]).is_equal_to(before["vendors"][1:])
    if field == "plugins":
        assert_that(mapping).does_not_contain_key("packages")
    else:
        package = mapping["packages"][0]
        assert_that(package["capabilities"]).is_equal_to({"teach": {"id": "stable"}})
        assert_that(package["x-package-note"]).is_equal_to("preserve")
        for optional in ("extraFiles", "renameSkills", "agents"):
            if optional == field:
                assert_that(package).does_not_contain_key(optional)
            else:
                assert_that(package[optional]).is_equal_to(
                    before["vendors"][0]["mapping"]["packages"][0][optional]
                )
    assert_that(legacy_documents(after)["vendors.yaml"]["vendors"]).is_equal_to(raw)


def test_management_add_update_and_writer_remove_are_lintable(
    author: Path, monkeypatch: pytest.MonkeyPatch, check_yaml: Callable[[Path], None]
) -> None:
    """Real author management mutations and removal roundtrip through the renderer."""
    # Acquisition is separate; exercise the real local write/validate path.
    monkeypatch.setattr(manage, "refresh", lambda **kwargs: write_legacy(author))
    path = author / "ai-skills.yaml"
    original = read_document(path)
    manage.add(
        repo_root=author,
        vendor_id="new-vendor",
        repo="example/new-vendor",
        sha="a" * 40,
        skill_roots=("skills",),
        license_name="MIT",
        homepage="https://example.test",
        display_ref=None,
        branch="main",
    )
    for name in ("ai-skills.yaml", "bundles.yaml", "vendors.yaml"):
        check_yaml(author / name)
    manage.update(
        repo_root=author,
        vendor_id="new-vendor",
        repo=None,
        sha="b" * 40,
        skill_roots=("skills", "extras"),
        license_name=None,
        homepage=None,
        display_ref=None,
        clear_branch=True,
    )
    assert_that(
        read_document(path)["vendors"][-1]["mapping"]["skillRoots"]
    ).is_equal_to(["skills", "extras"])
    for name in ("ai-skills.yaml", "bundles.yaml", "vendors.yaml"):
        check_yaml(author / name)
    raw = legacy_documents(read_document(path))["vendors.yaml"]["vendors"]
    manage._write_registry(registry_path=path, vendors=raw[:-1])
    assert_that(read_document(path)).is_equal_to(original)
    assert_that(write_legacy(author, check=True)).is_zero()
    for name in ("ai-skills.yaml", "bundles.yaml", "vendors.yaml"):
        check_yaml(author / name)
