"""Production inventory and artifact boundaries distinguish aliases from payloads."""

from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.selection.load import load_inputs

pytest_plugins = ["inventory_helpers"]


@pytest.mark.parametrize(
    "control",
    [
        "safe",
        "nested-safe",
        "escape",
        "absolute",
        "directory",
        "dangling",
        "chained",
        "cycle",
        "payload-file",
        "payload-directory",
        "resource",
        "extra-file",
    ],
)
def test_alias_policy_at_inventory_and_artifact_boundaries(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    control: str,
) -> None:
    """Unrelated safe aliases preserve tar identity; unsafe retained inputs fail."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    document["policy"] = {"provenance": {"mode": "strict"}}
    (root / "ai-skills.yaml").write_text(dump_document(document))
    args = ["--repo-root", str(root), "--vendor-root", f"vendor={vendor}"]
    assert_that(cli.main(["build", *args, "--write-digests"])).is_zero()
    capsys.readouterr()
    before = {
        path.name: path.read_bytes() for path in (root / "dist/artifacts").iterdir()
    }
    (vendor / "CLAUDE.md").write_text("Unselected regular documentation.\n")
    link = vendor / "AGENTS.md"
    target = "CLAUDE.md"
    if control == "nested-safe":
        link = vendor / "docs/navigation.md"
        link.parent.mkdir()
        target = "../CLAUDE.md"
    elif control == "escape":
        target = "../publisher/skills/start/SKILL.md"
    elif control == "absolute":
        target = str(vendor / "CLAUDE.md")
    elif control == "directory":
        target = "skills"
    elif control == "dangling":
        target = "absent.md"
    elif control == "chained":
        (vendor / "middle.md").symlink_to("CLAUDE.md")
        target = "middle.md"
    elif control == "cycle":
        target = "AGENTS.md"
    elif control == "payload-file":
        link = vendor / "skills/help/navigation.md"
        target = "SKILL.md"
    elif control == "payload-directory":
        link = vendor / "skills/help/assets"
        target = "../../agents"
    elif control == "resource":
        link = vendor / "NOTICE.md"
        link.unlink()
    elif control == "extra-file":
        package = document["vendors"][0]["mapping"]["packages"][0]
        package["extraFiles"].append("AGENTS.md")
        package["capabilities"]["help"]["resources"].append(
            "vendor/tools:resource/agents"
        )
        (root / "ai-skills.yaml").write_text(dump_document(document))
    link.symlink_to(target)
    expected = 0 if control in {"safe", "nested-safe"} else 1
    for command in (["inventory", "--json"], ["build", "--check"]):
        assert_that(cli.main([*command, *args])).is_equal_to(expected)
        output = capsys.readouterr()
        if expected:
            assert_that(output.out + output.err).contains(
                "inventory.invalid-"
                if control
                in {"payload-file", "payload-directory", "resource", "extra-file"}
                else "provenance.unverifiable-lineage"
            )
    assert_that(link.is_symlink()).is_true()
    assert_that(link.readlink().as_posix()).is_equal_to(target)
    assert_that(
        {path.name: path.read_bytes() for path in (root / "dist/artifacts").iterdir()}
    ).is_equal_to(before)


@pytest.mark.parametrize("empty", [False, True], ids=["ordinary", "empty"])
def test_unselected_alias_target_still_triggers_strict_missing_lineage(
    inventory_repo: tuple[Path, Path], empty: bool
) -> None:
    """Safe navigation aliases cannot conceal equal bytes outside import filters."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    document["policy"] = {"provenance": {"mode": "strict"}}
    (root / "ai-skills.yaml").write_text(dump_document(document))
    data = b"" if empty else b"Unselected source equality control.\n"
    (vendor / "CLAUDE.md").write_bytes(data)
    (vendor / "AGENTS.md").symlink_to("CLAUDE.md")
    (root / "skills/start/copied.txt").write_bytes(data)
    inventory, selection = load_inputs(root, vendor_roots={"vendor": vendor})
    findings = [
        item
        for item in inventory.diagnostics
        if item.code == "provenance.missing-lineage"
    ]
    assert_that(selection.valid).is_false()
    assert_that(findings).is_length(1)
    assert_that(findings[0].message).contains(
        "copied.txt", "byte equality, not authorship"
    )
    assert_that(findings[0].warning).is_false()
    assert_that(inventory.to_json()).does_not_contain("independentlyAuthored")


@pytest.mark.parametrize("data", [b"", b"\n", b"Shared bytes.\n"])
@pytest.mark.parametrize("exports", [[], ["a/tools"], ["a/tools", "b/tools"]])
def test_only_published_siblings_enter_the_publishers_equality_check(
    tmp_path: Path, data: bytes, exports: list[str]
) -> None:
    """Strict re-export checks preserve source identity without inventing history."""
    root = tmp_path / "catalog"
    root.mkdir()
    roots = {}
    vendors = []
    for name in ("a", "b"):
        source = tmp_path / name
        skill = source / "skills/helper"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: helper-{name}\ndescription: {name}.\n---\n{name}\n"
        )
        (skill / "__init__.py").write_bytes(data)
        roots[name] = source
        vendors.append(
            {
                "id": name,
                "repo": f"fixture/{name}",
                "sha": name * 40,
                "mapping": {
                    "skillRoots": ["skills"],
                    "packages": [
                        {"id": "tools", "skillsRoot": "skills", "skills": "*"}
                    ],
                },
            }
        )
    document = {
        "apiVersion": "ai-skills.dev/v1",
        "publisher": {"id": "catalog", "repo": "fixture/catalog"},
        "packages": [],
        "vendors": vendors,
        "exports": exports,
        "policy": {"provenance": {"mode": "strict"}},
    }
    (root / "ai-skills.yaml").write_text(dump_document(document))
    inventory, selection = load_inputs(root, vendor_roots=roots)
    findings = [item for item in inventory.diagnostics if not item.warning]
    assert_that(findings).is_length(len(exports))
    assert_that(selection.valid).is_equal_to(not exports)
    for finding in findings:
        assert_that(finding.code).is_equal_to("provenance.missing-lineage")
        assert_that(finding.message).contains(
            "__init__.py", "byte equality, not authorship"
        )
    for record in inventory.capabilities:
        assert_that(
            {hop.origin for chain in record.lineage for hop in chain.lineage}
        ).is_equal_to(
            {f"github.com/fixture/{record.package.publisher}"}
            | (
                {"github.com/fixture/catalog"}
                if str(record.package) in exports
                else set()
            )
        )
