"""Pure mapping selector counts and path-drift reconciliation on local trees."""

from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that
from repin_helpers import skill, write_tree

from ai_skills_engine.repin.mapping_selectors import analyze_mapping
from ai_skills_engine.repin.source_tree import SourceTree


def _trees(
    tmp_path: Path, old: dict[str, str], new: dict[str, str]
) -> tuple[SourceTree, SourceTree]:
    """Write two revisions.

    Args:
        tmp_path: Test directory.
        old: Previous tree.
        new: Current tree.

    Returns:
        Hashed previous and current trees.
    """
    write_tree(dest=tmp_path / "old", tree=old)
    write_tree(dest=tmp_path / "new", tree=new)
    return SourceTree(tmp_path / "old"), SourceTree(tmp_path / "new")


def _entry(**package: Any) -> dict[str, Any]:
    """Build a vendor declaration with one mapped package.

    Args:
        **package: Mapped package fields overriding the defaults.

    Returns:
        Vendor declaration.
    """
    return {
        "id": "example",
        "mapping": {
            "skillRoots": ["skills"],
            "packages": [
                {"id": "tools", "skillsRoot": "skills", "skills": "*", **package}
            ],
        },
    }


def test_paths_reconcile_extra_skills_files_and_resources(tmp_path: Path) -> None:
    """Every path-bearing mapping field is rewritten for one unique move."""
    old, new = _trees(
        tmp_path,
        {
            "skills/a/SKILL.md": skill("a", "a"),
            "extra/b/SKILL.md": skill("b", "b"),
            "docs/NOTES.md": "notes\n",
            "assets/logo.txt": "logo\n",
        },
        {
            "skills/a/SKILL.md": skill("a", "a"),
            "more/b/SKILL.md": skill("b", "b"),
            "documentation/NOTES.md": "notes\n",
            "media/logo.txt": "logo\n",
        },
    )
    plan = analyze_mapping(
        entry=_entry(
            extraSkills=["extra/b"],
            extraFiles=["docs/NOTES.md"],
            artifactResources={
                "version": 1,
                "resources": [{"id": "logo", "path": "assets/logo.txt"}],
                "bindings": {},
            },
        ),
        old=old,
        new=new,
    )
    assert_that(plan.failures).is_empty()
    package = plan.entry["mapping"]["packages"][0]
    assert_that(package["extraSkills"]).is_equal_to(["more/b"])
    assert_that(package["extraFiles"]).is_equal_to(["documentation/NOTES.md"])
    assert_that(package["artifactResources"]["resources"][0]["path"]).is_equal_to(
        "media/logo.txt"
    )
    assert_that({item.status for item in plan.drifts}).is_equal_to({"reconciled"})


def test_skill_roots_reconcile_and_dead_glob_fails(tmp_path: Path) -> None:
    """A literal discovery root moves; a glob root matching nothing fails."""
    old, new = _trees(
        tmp_path,
        {"skills/a/SKILL.md": skill("a", "a")},
        {"src/skills/a/SKILL.md": skill("a", "a")},
    )
    entry = _entry(skillsRoot="plugins/*/skills")
    plan = analyze_mapping(entry=entry, old=old, new=new)
    assert_that(plan.entry["mapping"]["skillRoots"]).is_equal_to(["src/skills"])
    assert_that("\n".join(plan.failures)).contains(
        "mapping.packages[tools].skillsRoot: 'plugins/*/skills'"
    )


def test_agents_and_unused_declaration_keys_fail(tmp_path: Path) -> None:
    """Agents cannot move; stale renameSkills/capabilities keys are dead."""
    old, new = _trees(
        tmp_path,
        {
            "skills/a/SKILL.md": skill("a", "a"),
            "agents/helper.md": "helper\n",
        },
        {
            "skills/a/SKILL.md": skill("a", "a"),
            "elsewhere/helper.md": "helper\n",
        },
    )
    plan = analyze_mapping(
        entry=_entry(
            agents=["helper"],
            renameSkills={"gone": "renamed"},
            capabilities={"a": {}},
        ),
        old=old,
        new=new,
    )
    failures = "\n".join(plan.failures)
    assert_that(failures).contains("'helper'", "renameSkills: 'gone'")
    assert_that(failures).does_not_contain("capabilities: 'a'")
    assert_that([item.candidates for item in plan.drifts]).contains(
        ("elsewhere/helper.md",)
    )


@pytest.mark.parametrize("old_tree", [True, False], ids=["empty", "new-vendor"])
def test_wildcard_matching_nothing_fails(tmp_path: Path, old_tree: bool) -> None:
    """``skills: '*'`` under a root with no skills is a dead selector."""
    old, new = _trees(
        tmp_path, {"skills/a/SKILL.md": skill("a", "a")}, {"skills/README.md": "x\n"}
    )
    plan = analyze_mapping(entry=_entry(), old=old if old_tree else None, new=new)
    assert_that("\n".join(plan.failures)).contains(
        "mapping.packages[tools].skills: '*'"
    )


def test_root_move_by_unique_members(tmp_path: Path) -> None:
    """A changed root still reconciles when every member moved to one parent."""
    old, new = _trees(
        tmp_path,
        {
            "skills/a/SKILL.md": skill("a", "a"),
            "skills/b/SKILL.md": skill("b", "b"),
            "skills/README.md": "old readme\n",
        },
        {
            "pkg/skills/a/SKILL.md": skill("a", "a"),
            "pkg/skills/b/SKILL.md": skill("b", "b"),
            "pkg/skills/README.md": "new readme\n",
        },
    )
    plan = analyze_mapping(entry=_entry(skills=["a", "b"]), old=old, new=new)
    assert_that(plan.failures).is_empty()
    assert_that(plan.entry["mapping"]["packages"][0]["skillsRoot"]).is_equal_to(
        "pkg/skills"
    )


def test_root_members_split_across_parents_fail(tmp_path: Path) -> None:
    """Members moving to different parents cannot rewrite one root."""
    old, new = _trees(
        tmp_path,
        {"skills/a/SKILL.md": skill("a", "a"), "skills/b/SKILL.md": skill("b", "b")},
        {"x/a/SKILL.md": skill("a", "a"), "y/b/SKILL.md": skill("b", "b")},
    )
    plan = analyze_mapping(entry=_entry(skills=["a", "b"]), old=old, new=new)
    assert_that(plan.failures).is_not_empty()
    assert_that([item.status for item in plan.drifts]).contains("ambiguous")
