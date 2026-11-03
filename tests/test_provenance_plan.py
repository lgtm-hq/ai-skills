"""Provenance at the actual recursive loader, planner and public CLI boundaries."""

import json
from pathlib import Path

import pytest
from assertpy import assert_that
from inventory_helpers import snapshot
from jsonschema import Draft202012Validator
from provenance_helpers import (
    change_policy,
    missing_copy,
    unbound_copy,
    vendor_roots,
)

from ai_skills_engine import cli
from ai_skills_engine.inventory.load import load_inventory
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.provenance.ingest import schema
from ai_skills_engine.selection.load import load_selection


def test_two_hop_denies_renames_transforms_and_shared_copies(
    provenance_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every X-derived record is vetoed; both resource requirers remain visible."""
    root = provenance_repo
    before = snapshot(root)
    result = load_selection(root / "z", vendor_roots=vendor_roots(root))
    assert_that(result.valid).is_false()
    assert_that(
        {item.state for item in (*result.capabilities, *result.resources)}
    ).is_equal_to({"denied"})
    copied = result.resources[0]
    assert_that(copied.id).is_equal_to("x/tools:resource/script")
    for chain in copied.lineage:
        assert_that([hop.origin for hop in chain.lineage]).contains(
            "github.com/fixture/x", "github.com/fixture/y"
        )
    transformed = next(
        item for item in result.capabilities if item.id == "y/tools:skill/transformed"
    )
    assert_that(transformed.lineage[0].lineage[-1].transforms).contains(
        "frontmatter-name"
    )
    renamed = next(
        item for item in result.capabilities if item.id == "y/tools:skill/renamed"
    )
    assert_that(renamed.lineage[0].lineage[-1].renamed_from).is_equal_to(
        "y/tools:skill/excel"
    )
    args = [
        "plan",
        "--repo-root",
        str(root / "z"),
        "--vendor-root",
        f"y={root / 'y'}",
        "--vendor-root",
        f"y/x={root / 'x'}",
    ]
    assert_that(cli.main(args)).is_equal_to(1)
    text = capsys.readouterr().out
    assert_that(text).contains(
        "github.com/fixture/x@",
        "github.com/fixture/y@",
        "z/tools:skill/first",
        "z/tools:skill/second",
        "x/tools:resource/script",
    )
    assert_that(snapshot(root)).is_equal_to(before)


def test_plan_json_determinism_and_packaged_schema(
    provenance_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Public JSON embeds validated deterministic chains, including copied resources."""
    root = provenance_repo
    change_policy(root=root / "z")
    args = [
        "plan",
        "--json",
        "--repo-root",
        str(root / "z"),
        "--vendor-root",
        f"y={root / 'y'}",
        "--vendor-root",
        f"y/x={root / 'x'}",
    ]
    assert_that(cli.main(args)).is_zero()
    first = capsys.readouterr().out
    assert_that(cli.main(args)).is_zero()
    assert_that(capsys.readouterr().out).is_equal_to(first)
    data = json.loads(first)
    validator = Draft202012Validator(schema())
    for entry in (*data["capabilities"], *data["resources"]):
        assert_that(entry["lineage"]).is_not_empty()
        for chain in entry["lineage"]:
            assert_that(list(validator.iter_errors(chain))).is_empty()
    resource = data["resources"][0]
    assert_that(
        [chain["lineage"][-1]["path"] for chain in resource["lineage"]]
    ).contains("_shared")


@pytest.mark.parametrize(
    ("mode", "accepted", "statement", "expected"),
    [
        ("warn", False, False, 0),
        ("strict", False, False, 1),
        ("strict", False, True, 1),
        ("strict", True, True, 0),
    ],
)
def test_missing_lineage_uses_full_pinned_tree_and_consumer_policy(
    provenance_repo: Path, mode: str, accepted: bool, statement: bool, expected: int
) -> None:
    """Vendor policy never clears a full-tree equality diagnostic by itself."""
    root = provenance_repo
    missing_copy(root=root, statement=statement)
    change_policy(root=root / "z", mode=mode, accept=accepted)
    before = snapshot(root)
    result = load_selection(root / "z", vendor_roots=vendor_roots(root))
    assert_that(int(not result.valid)).is_equal_to(expected)
    diagnostics = [
        item for item in result.diagnostics if item.code == "provenance.missing-lineage"
    ]
    if statement and accepted:
        assert_that(diagnostics).is_empty()
    else:
        assert_that(diagnostics).is_length(1)
        assert_that(diagnostics[0].warning).is_equal_to(mode == "warn")
        assert_that(diagnostics[0].message).contains(
            "byte equality, not authorship", "proof.txt", "github.com/fixture/x@"
        )
    copy = next(item for item in result.capabilities if item.id == "y/tools:skill/copy")
    assert_that(
        {hop.origin for chain in copy.lineage for hop in chain.lineage}
    ).is_equal_to({"github.com/fixture/y"})
    assert_that(snapshot(root)).is_equal_to(before)


def test_independent_identical_bytes_do_not_gain_ancestry(
    provenance_repo: Path,
) -> None:
    """No import means no diagnostic or deny merely from bytes found elsewhere."""
    root = provenance_repo
    independent = root / "independent"
    independent.mkdir()
    (independent / "plain").mkdir()
    (independent / "plain/SKILL.md").write_bytes(
        (root / "x/skills/plain/SKILL.md").read_bytes()
    )
    (independent / "ai-skills.yaml").write_text(
        dump_document(
            {
                "apiVersion": "ai-skills.dev/v1",
                "publisher": {"id": "independent", "repo": "fixture/independent"},
                "packages": [
                    {"id": "tools", "capabilities": [{"id": "plain", "path": "plain"}]}
                ],
                "policy": {
                    "deny": {"origins": ["github.com/fixture/x"]},
                    "provenance": {"mode": "strict"},
                },
            }
        )
    )
    result = load_selection(independent)
    assert_that(result.valid).is_true()
    assert_that(result.capabilities[0].state).is_equal_to("selected")
    assert_that([item.code for item in result.diagnostics]).does_not_contain(
        "provenance.missing-lineage"
    )
    assert_that(
        {
            hop.origin
            for chain in result.capabilities[0].lineage
            for hop in chain.lineage
        }
    ).is_equal_to({"github.com/fixture/independent"})


@pytest.mark.parametrize(
    "control",
    ["known-lineage", "deny-import", "deny-current", "wrong-path", "resource-deny"],
)
def test_attestations_never_override_known_lineage_or_consumer_vetoes(
    provenance_repo: Path, control: str
) -> None:
    """Claims cannot override imported ancestry, resource denies or org vetoes."""
    root = provenance_repo
    missing_copy(
        root=root,
        statement=True,
        statement_path="wrong.txt" if control == "wrong-path" else "proof.txt",
    )
    deny = (
        ("github.com/fixture/y",)
        if control == "deny-current"
        else (
            ("github.com/fixture/x",)
            if control in {"deny-import", "resource-deny"}
            else ()
        )
    )
    change_policy(root=root / "z", accept=True, deny=deny)
    path = root / "y/ai-skills.yaml"
    document = read_document(path)
    if control == "known-lineage":
        document["overrides"]["attestations"][0]["capability"] = "y/tools:skill/renamed"
    elif control == "resource-deny":
        document["packages"][0]["capabilities"][-1]["resources"] = [
            "x/tools:resource/script"
        ]
    path.write_text(dump_document(document))
    result = load_selection(root / "z", vendor_roots=vendor_roots(root))
    assert_that(result.valid).is_false()
    codes = [item.code for item in result.diagnostics]
    assert_that(codes).contains("provenance.missing-lineage")
    if control != "wrong-path":
        assert_that(codes).contains("provenance.attestation-conflicts-lineage")


def test_recursive_exports_are_explicit_and_follow_pins(provenance_repo: Path) -> None:
    """A private nested import never appears just because its publisher imported it."""
    root = provenance_repo
    change_policy(root=root / "z")
    path = root / "y/ai-skills.yaml"
    document = read_document(path)
    document["exports"] = ["tools"]
    path.write_text(dump_document(document))
    index = root / "y/ai-skills.lineage.json"
    index.write_text(
        json.dumps(
            [
                item
                for item in json.loads(index.read_text())
                if item["id"].startswith("y/")
            ]
        )
    )
    result = load_inventory(root / "z", vendor_roots=vendor_roots(root))
    assert_that([str(item.id) for item in result.capabilities]).does_not_contain(
        "x/tools:skill/plain"
    )
    assert_that([str(item.id) for item in result.resources]).does_not_contain(
        "x/tools:resource/script"
    )


def test_missing_recursive_pin_fails_strict(provenance_repo: Path) -> None:
    """A missing nested snapshot cannot silently certify publisher provenance."""
    root = provenance_repo
    change_policy(root=root / "z")
    result = load_selection(root / "z", vendor_roots={"y": root / "y"})
    assert_that(result.valid).is_false()
    assert_that([item.code for item in result.diagnostics]).contains(
        "provenance.unverifiable-lineage"
    )


@pytest.mark.parametrize("target", ["x/tools:skill/plain", "x/tools:resource/script"])
def test_consumer_excludes_recursive_candidates_without_erasing_lineage(
    provenance_repo: Path, target: str
) -> None:
    """Recursive candidates remain visible to vetoes and required-edge failures."""
    root = provenance_repo
    change_policy(root=root / "z")
    path = root / "z/ai-skills.yaml"
    document = read_document(path)
    document["vendors"][0]["exclude"] = [target]
    if ":skill/" in target:
        document["packages"][0]["capabilities"][0]["requires"] = [target]
    path.write_text(dump_document(document))
    result = load_selection(root / "z", vendor_roots=vendor_roots(root))
    entries = {item.id: item for item in (*result.capabilities, *result.resources)}
    assert_that(entries[target].state).is_equal_to("excluded")
    assert_that(entries[target].lineage).is_not_empty()
    assert_that([item.code for item in result.diagnostics]).contains(
        "selection.required-excluded"
    ).does_not_contain("selection.selector-unmatched")


def test_consumer_attestation_is_descriptive_and_subject_to_final_policy(
    provenance_repo: Path,
) -> None:
    """A final consumer can supply a claim without importing publisher trust policy."""
    root = provenance_repo
    missing_copy(root=root)
    change_policy(root=root / "z", accept=True)
    path = root / "z/ai-skills.yaml"
    document = read_document(path)
    document["overrides"] = {
        "attestations": [
            {
                "capability": "y/tools:skill/copy",
                "path": "proof.txt",
                "independentlyAuthored": True,
                "reason": "Consumer verified independent authorship.",
            }
        ]
    }
    path.write_text(dump_document(document))
    result = load_selection(root / "z", vendor_roots=vendor_roots(root))
    assert_that(result.valid).is_true()
    claim = next(
        item for item in result.capabilities if item.id == "y/tools:skill/copy"
    )
    assert_that(claim.lineage[0].attestations).is_length(1)
    change_policy(root=root / "z", accept=False)
    assert_that(
        load_selection(root / "z", vendor_roots=vendor_roots(root)).valid
    ).is_false()


def test_inventory_json_uses_the_lineage_schema(provenance_repo: Path) -> None:
    """Inventory and plan expose the same packaged camelCase lineage contract."""
    root = provenance_repo
    inventory = load_inventory(root / "z", vendor_roots=vendor_roots(root))
    data = json.loads(inventory.to_json())
    validator = Draft202012Validator(schema())
    for record in (*data["capabilities"], *data["resources"]):
        assert_that(record["lineage"]).is_not_empty()
        for chain in record["lineage"]:
            assert_that(list(validator.iter_errors(chain))).is_empty()


def test_migrated_nested_resource_edges_resolve_after_recursive_exports(
    provenance_repo: Path,
) -> None:
    """A migrated selector binds its real nested target without stale missing errors."""
    root = provenance_repo
    change_policy(root=root / "z")
    path = root / "z/ai-skills.yaml"
    document = read_document(path)
    document["packages"][0]["capabilities"][0]["resources"] = [
        "x/tools:resource/old-script"
    ]
    document["overrides"] = {
        "migrations": [
            {"from": "x/tools:resource/old-script", "to": "x/tools:resource/script"}
        ]
    }
    path.write_text(dump_document(document))
    result = load_selection(root / "z", vendor_roots=vendor_roots(root))
    assert_that(result.valid).is_true()
    assert_that([item.code for item in result.diagnostics]).does_not_contain(
        "inventory.unknown-resources"
    )


@pytest.mark.parametrize("author", ["publisher", "consumer"])
def test_publisher_dependency_migrations_survive_recursive_resolution(
    provenance_repo: Path, author: str
) -> None:
    """Validated identity moves resolve publisher edges without importing authority."""
    root = provenance_repo
    change_policy(root=root / "z")
    path = root / "y/ai-skills.yaml"
    document = read_document(path)
    document["packages"][0]["capabilities"][0]["requires"] = [
        "y/tools:skill/old-transformed"
    ]
    move = {"from": "y/tools:skill/old-transformed", "to": "y/tools:skill/transformed"}
    if author == "publisher":
        document["overrides"]["migrations"].append(move)
    path.write_text(dump_document(document))
    if author == "consumer":
        consumer_path = root / "z/ai-skills.yaml"
        consumer = read_document(consumer_path)
        consumer["overrides"] = {"migrations": [move]}
        consumer_path.write_text(dump_document(consumer))
    result = load_selection(root / "z", vendor_roots=vendor_roots(root))
    assert_that(result.valid).is_true()
    assert_that([item.code for item in result.diagnostics]).does_not_contain(
        "inventory.unknown-requires", "selection.required-missing"
    )


@pytest.mark.parametrize(
    "control", ["missing-copy", "outside-boundary", "unverifiable-warn"]
)
def test_resolved_shared_links_remain_fail_closed(
    provenance_repo: Path, control: str
) -> None:
    """Real copied-resource links need verified bytes and an explicit boundary."""
    from provenance_helpers import refresh_index

    root = provenance_repo
    change_policy(
        root=root / "z", mode="warn" if control == "unverifiable-warn" else "strict"
    )
    if control == "missing-copy":
        (root / "y/_shared/copied.py").unlink()
    elif control == "outside-boundary":
        target = root / "y/unrelated.txt"
        target.write_text("Not an authorized resource.\n")
        cap = root / "y/skills/renamed/SKILL.md"
        cap.write_text(cap.read_text() + "\n[Unrelated](../../unrelated.txt).\n")
        refresh_index(root)
    else:
        (root / "y/ai-skills.lineage.json").write_text("[")
    result = load_selection(root / "z", vendor_roots=vendor_roots(root))
    assert_that(result.valid).is_false()
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.undeclared-resource"
    )


def test_equal_local_resource_copy_needs_a_current_publication_hop(
    provenance_repo: Path,
) -> None:
    """Hash equality cannot authorize a local copy under another resource's ID."""
    root = provenance_repo
    change_policy(root=root / "z")
    unbound_copy(root)
    result = load_selection(root / "z", vendor_roots=vendor_roots(root))
    assert_that(result.valid).is_false()
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.undeclared-resource"
    )
    assert_that(
        {hop.origin for chain in result.resources[0].lineage for hop in chain.lineage}
    ).does_not_contain("github.com/fixture/z")
