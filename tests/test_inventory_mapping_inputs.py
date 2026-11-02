"""Actual inventory mapping handles glob boundaries and fails resource collisions."""

import shutil
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.inventory import load_inventory
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document

pytest_plugins = ["inventory_helpers"]


@pytest.mark.parametrize(
    "pattern,roots",
    [
        ("skills/team-*", ["skills/team-alpha"]),
        ("skills/team-?", ["skills/team-a"]),
        ("skills/team-[ab]", ["skills/team-a", "skills/team-b"]),
        ("skills/team-*", ["skills/team-alpha", "skills/team-beta"]),
        ("skills-*", ["skills-core"]),
        ("skills/team-alpha", ["skills/team-alpha"]),
        ("skills/missing-*", []),
        ("skills/missing", []),
    ],
    ids=[
        "suffix",
        "question",
        "class",
        "multiple",
        "top-level",
        "literal",
        "missing-glob",
        "missing-literal",
    ],
)
def test_glob_validates_complete_ancestors_and_real_matches(
    inventory_repo: tuple[Path, Path], pattern: str, roots: list[str]
) -> None:
    """Partial component prefixes need not exist; actual matches must be safe."""
    root, vendor = inventory_repo
    for index, relative in enumerate(roots):
        shutil.copytree(
            src=vendor / "skills/help", dst=vendor / relative / f"help-{index}"
        )
    document = read_document(root / "ai-skills.yaml")
    package = document["vendors"][0]["mapping"]["packages"][0]
    package["skillsRoot"] = pattern
    package["capabilities"] = {}
    package.pop("renameSkills")
    document["packages"][0]["capabilities"][0]["requires"] = []
    for path in vendor.glob("**/help-*/SKILL.md"):
        path.write_text("---\nname: help\ndescription: Safe.\n---\n")
    (root / "ai-skills.yaml").write_text(dump_document(document))
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    errors = [item for item in result.diagnostics if not item.warning]
    if roots:
        assert_that(errors).is_empty()
        assert_that(
            [
                str(item.id)
                for item in result.capabilities
                if item.id.role == "skill" and item.id.package.publisher == "vendor"
            ]
        ).is_length(len(roots))
    else:
        assert_that([item.code for item in errors]).contains(
            "inventory.invalid-payload"
        )


@pytest.mark.parametrize("boundary", ["ancestor", "matched", "intermediate"])
def test_glob_cannot_follow_symlink_boundaries(
    inventory_repo: tuple[Path, Path], tmp_path: Path, boundary: str
) -> None:
    """Literal ancestors, matched roots and globbed intermediate links fail closed."""
    root, vendor = inventory_repo
    target = tmp_path / "outside"
    shutil.copytree(src=vendor / "skills", dst=target)
    document = read_document(root / "ai-skills.yaml")
    package = document["vendors"][0]["mapping"]["packages"][0]
    package["capabilities"] = {}
    package.pop("renameSkills")
    document["packages"][0]["capabilities"][0]["requires"] = []
    if boundary == "ancestor":
        shutil.rmtree(vendor / "skills")
        (vendor / "skills").symlink_to(target, target_is_directory=True)
        package["skillsRoot"] = "skills/team-*"
    elif boundary == "matched":
        (vendor / "skills/team-alpha").symlink_to(target, target_is_directory=True)
        package["skillsRoot"] = "skills/team-*"
    else:
        (vendor / "skills/team-alpha").symlink_to(target, target_is_directory=True)
        package["skillsRoot"] = "skills/team-*/help"
    (root / "ai-skills.yaml").write_text(dump_document(document))
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that(
        [item.message for item in result.diagnostics if not item.warning]
    ).is_not_empty()
    assert_that(" ".join(item.message for item in result.diagnostics)).contains(
        "symlink rejected"
    )


@pytest.mark.parametrize("collision", [True, False], ids=["collision", "distinct"])
def test_extra_files_collision_is_cli_failure_with_both_paths(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    collision: bool,
) -> None:
    """Documented notice IDs stay stable; colliding paths cannot report success."""
    root, vendor = inventory_repo
    paths = [
        "docs/NOTICE.md",
        "licenses/NOTICE.txt" if collision else "licenses/LICENSE.txt",
    ]
    for relative in paths:
        path = vendor / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Resource.\n")
    document = read_document(root / "ai-skills.yaml")
    document["vendors"][0]["mapping"]["packages"][0]["extraFiles"] = paths
    (root / "ai-skills.yaml").write_text(dump_document(document))
    skill = vendor / "skills/help/SKILL.md"
    skill.write_text(
        skill.read_text().replace("../../NOTICE.md", "../../docs/NOTICE.md")
    )
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that(
        cli.main(
            [
                "inventory",
                "--repo-root",
                str(root),
                "--vendor-root",
                f"vendor={vendor}",
                "--json",
            ]
        )
    ).is_equal_to(int(collision))
    output = capsys.readouterr().out
    assert_that(output).is_equal_to(result.to_json())
    if collision:
        finding = next(
            item for item in result.diagnostics if item.code == "inventory.duplicate-id"
        )
        assert_that(finding.warning).is_false()
        assert_that(finding.message).contains(*paths)
    else:
        assert_that(
            [item for item in result.diagnostics if not item.warning]
        ).is_empty()
