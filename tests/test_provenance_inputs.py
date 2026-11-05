"""Production inventory and artifact boundaries distinguish aliases from payloads."""

import json
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.inventory.payload import payload_files, tree_digest
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
    assert_that(cli.main(["lock", *args])).is_zero()
    assert_that(cli.main(["build", "--repo-root", str(root)])).is_zero()
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
    rebuilt = root / "rebuilt"
    commands = (
        ["inventory", "--json"],
        ["bake", "artifacts", "--output", str(rebuilt)],
    )
    for command in commands:
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
    if not expected:
        # Safe unrelated aliases preserve the reviewed tar identity exactly.
        assert_that(
            {path.name: path.read_bytes() for path in rebuilt.iterdir()}
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
@pytest.mark.parametrize("control", ["reexport", "local", "unbound", "forged"])
def test_verified_reexports_use_their_source_publishers_input_scope(
    tmp_path: Path, data: bytes, exports: list[str], control: str
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
    if control in {"local", "unbound"}:
        payload = root / "skills/copy"
        payload.mkdir(parents=True)
        (payload / "SKILL.md").write_text(
            "---\nname: local-copy\ndescription: Local.\n---\nCatalog wrapper.\n"
        )
        (payload / "__init__.py").write_bytes(data)
        document["packages"] = [
            {"id": "local", "capabilities": [{"id": "copy", "path": "skills/copy"}]}
        ]
    if control in {"unbound", "forged"}:
        publisher = "catalog" if control == "unbound" else "a"
        source = root if control == "unbound" else roots["a"]
        identity = (
            "catalog/local:skill/copy"
            if control == "unbound"
            else "a/tools:skill/helper"
        )
        relative = "skills/copy" if control == "unbound" else "skills/helper"
        (source / "ai-skills.lineage.json").write_text(
            json.dumps(
                [
                    {
                        "id": identity,
                        "lineage": [
                            {
                                "origin": "github.com/fixture/forged",
                                "publisher": publisher,
                                "rev": "a" * 40,
                                "id": identity,
                                "path": relative,
                                "treeDigest": "sha256:"
                                + tree_digest(payload_files(source / relative)),
                            }
                        ],
                    }
                ]
            )
        )
    (root / "ai-skills.yaml").write_text(dump_document(document))
    inventory, selection = load_inputs(root, vendor_roots=roots)
    findings = [item for item in inventory.diagnostics if not item.warning]
    codes = [item.code for item in findings]
    assert_that(selection.valid).is_equal_to(control == "reexport")
    if control == "reexport":
        assert_that(findings).is_empty()
    if control in {"local", "unbound"}:
        missing = [
            item for item in findings if item.code == "provenance.missing-lineage"
        ]
        assert_that(missing).is_length(1)
        assert_that(missing[0].message).contains(
            "__init__.py", "byte equality, not authorship"
        )
    if control in {"unbound", "forged"}:
        assert_that(codes).contains("provenance.unverifiable-lineage")
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


@pytest.mark.parametrize("control", ["deny", "attestation"])
def test_source_scoped_reexports_retain_denies_and_attestation_conflicts(
    inventory_repo: tuple[Path, Path], control: str
) -> None:
    """Verified source scope cannot clear consumer vetoes or conflicting claims."""
    root, vendor = inventory_repo
    path = root / "ai-skills.yaml"
    document = read_document(path)
    document["policy"] = {"provenance": {"mode": "strict", "acceptAttestations": True}}
    if control == "deny":
        document["policy"]["deny"] = {"origins": ["github.com/upstream/tools"]}
    else:
        document["overrides"] = {
            "attestations": [
                {
                    "capability": "vendor/tools:skill/helper",
                    "path": "SKILL.md",
                    "independentlyAuthored": True,
                    "reason": "Conflicting control claim.",
                }
            ]
        }
    path.write_text(dump_document(document))
    _, selection = load_inputs(root, vendor_roots={"vendor": vendor})
    assert_that(selection.valid).is_false()
    assert_that([item.code for item in selection.diagnostics]).contains(
        "selection.required-denied"
        if control == "deny"
        else "provenance.attestation-conflicts-lineage"
    )
