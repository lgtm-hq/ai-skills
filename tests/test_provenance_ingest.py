"""Authenticated last-hop, migration, cycle and ancestry-union controls."""

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from assertpy import assert_that
from provenance_helpers import change_policy, omit_shared_links, vendor_roots

from ai_skills_engine.inventory.load import load_inventory
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.provenance.model import union_lineage
from ai_skills_engine.selection.load import load_selection


@pytest.mark.parametrize(
    "control",
    [
        "origin",
        "rev",
        "id",
        "publisher",
        "digest",
        "path",
        "cycle",
        "duplicate",
        "malformed",
        "unknown-key",
        "ancestor-rev",
    ],
)
@pytest.mark.parametrize("mode", ["strict", "warn"])
def test_ingested_lineage_must_bind_to_pinned_publication_and_bytes(
    provenance_repo: Path, control: str, mode: str
) -> None:
    """A vendor cannot certify another origin/revision or a different payload."""
    root = provenance_repo
    omit_shared_links(root)
    change_policy(root=root / "z", mode=mode)
    index = root / "y/ai-skills.lineage.json"
    records = json.loads(index.read_text())
    last = records[0]["lineage"][-1]
    if control == "origin":
        last["origin"] = "github.com/fixture/impostor"
    elif control == "rev":
        last["rev"] = "c" * 40
    elif control == "id":
        last["id"] = "y/tools:skill/other"
    elif control == "publisher":
        last["publisher"] = "impostor"
    elif control == "digest":
        last["treeDigest"] = "sha256:" + "0" * 64
    elif control == "path":
        last["path"] = "skills/transformed"
    elif control == "cycle":
        records[0]["lineage"].insert(0, dict(records[0]["lineage"][0]))
    elif control == "duplicate":
        records.append(records[0])
    elif control == "unknown-key":
        last["trust"] = True
    elif control == "ancestor-rev":
        records[0]["lineage"][0]["rev"] = None
    index.write_text("[" if control == "malformed" else json.dumps(records))
    result = load_selection(root / "z", vendor_roots=vendor_roots(root))
    evidence = [
        item
        for item in result.diagnostics
        if item.code == "provenance.unverifiable-lineage"
    ]
    assert_that(evidence).is_not_empty()
    assert_that({item.warning for item in evidence}).is_equal_to({mode == "warn"})
    assert_that(result.valid).is_equal_to(mode == "warn")


def test_reexport_cycle_fails_closed(provenance_repo: Path) -> None:
    """Actual recursive pin resolution rejects X/Y re-export cycles."""
    root = provenance_repo
    change_policy(root=root / "z")
    path = root / "x/ai-skills.yaml"
    document = read_document(path)
    document["vendors"] = [{"id": "y", "repo": "fixture/y", "sha": "b" * 40}]
    document["exports"].append("y/tools")
    path.write_text(dump_document(document))
    roots = vendor_roots(root)
    roots["y/x/y"] = root / "y"
    roots["y/x/y/x"] = root / "x"
    result = load_selection(root / "z", vendor_roots=roots)
    assert_that(result.valid).is_false()
    cycle = next(
        item for item in result.diagnostics if item.code == "provenance.reexport-cycle"
    )
    assert_that(cycle.message).contains("github.com/fixture/x", "github.com/fixture/y")


@pytest.mark.parametrize("explicit", [False, True])
def test_identity_change_preserves_ancestry_only_with_migration(
    provenance_repo: Path, explicit: bool
) -> None:
    """Mapped migrations carry old chains; unmapped IDs begin fresh and remove old."""
    root = provenance_repo
    change_policy(root=root / "z")
    path = root / "y/ai-skills.yaml"
    document = read_document(path)
    document["packages"][0]["capabilities"][1]["id"] = "new-id"
    if explicit:
        document["overrides"]["migrations"].append(
            {"from": "y/tools:skill/transformed", "to": "y/tools:skill/new-id"}
        )
    path.write_text(dump_document(document))
    index = root / "y/ai-skills.lineage.json"
    records = json.loads(index.read_text())
    if not explicit:
        index.write_text(
            json.dumps(
                [item for item in records if item["id"] != "y/tools:skill/transformed"]
            )
        )
    inventory = load_inventory(root / "z", vendor_roots=vendor_roots(root))
    cap = next(item for item in inventory.capabilities if item.id.name == "new-id")
    assert_that([str(item.id) for item in inventory.capabilities]).does_not_contain(
        "y/tools:skill/transformed"
    )
    origins = {hop.origin for chain in cap.lineage for hop in chain.lineage}
    assert_that("github.com/fixture/x" in origins).is_equal_to(explicit)
    if explicit:
        assert_that(cap.lineage[0].lineage[-1].renamed_from).is_equal_to(
            "y/tools:skill/transformed"
        )
        assert_that(cap.lineage[0].lineage).is_length(3)
    else:
        assert_that(cap.lineage[0].lineage).is_length(1)


def test_resource_copy_and_dedup_keep_union_of_all_chains(
    provenance_repo: Path,
) -> None:
    """Copied-resource ingestion unions index and recursively resolved ancestry."""
    root = provenance_repo
    change_policy(root=root / "z", deny=("github.com/fixture/earlier",))
    index = root / "y/ai-skills.lineage.json"
    records = json.loads(index.read_text())
    resource = next(item for item in records if item["id"] == "x/tools:resource/script")
    hop = dict(resource["lineage"][0])
    hop.update(
        origin="github.com/fixture/earlier",
        publisher="earlier",
        id="earlier/tools:resource/script",
    )
    resource["lineage"].insert(0, hop)
    index.write_text(json.dumps(records))
    result = load_selection(root / "z", vendor_roots=vendor_roots(root))
    assert_that(result.valid).is_false()
    entry = result.resources[0]
    assert_that(entry.lineage).is_length(2)
    assert_that(
        {hop.origin for chain in entry.lineage for hop in chain.lineage}
    ).contains(
        "github.com/fixture/earlier", "github.com/fixture/x", "github.com/fixture/y"
    )
    assert_that(
        {item.state for item in result.capabilities if item.id.startswith("z/")}
    ).is_equal_to({"denied"})
    requirers = {
        item.location
        for item in result.diagnostics
        if item.code == "selection.required-denied"
    }
    assert_that(requirers).contains("z/tools:skill/first", "z/tools:skill/second")
    assert_that(
        union_lineage(entry.lineage, tuple(reversed(entry.lineage)), entry.lineage)
    ).is_equal_to(entry.lineage)
    chain = entry.lineage[0]
    assert_that(chain.to_json()).is_equal_to(replace(chain).to_json())
    attribute = "origin"
    with pytest.raises(FrozenInstanceError):
        setattr(chain.lineage[0], attribute, "changed")


def test_local_and_manifestless_lineage_have_one_origin_hop(
    provenance_repo: Path,
) -> None:
    """Local uncommitted and mapped pin identities use the same production loader."""
    root = provenance_repo
    path = root / "z/ai-skills.yaml"
    document = read_document(path)
    document["vendors"] = [
        {
            "id": "mapped",
            "repo": "fixture/x",
            "sha": "a" * 40,
            "mapping": {"skillRoots": ["skills"]},
        }
    ]
    document["packages"][0]["capabilities"] = [{"id": "first", "path": "skills/first"}]
    path.write_text(dump_document(document))
    (root / "x/ai-skills.yaml").unlink()
    inventory = load_inventory(root / "z", vendor_roots={"mapped": root / "x"})
    mapped = next(
        item for item in inventory.capabilities if item.id.package.publisher == "mapped"
    )
    assert_that(mapped.lineage).is_length(1)
    assert_that(mapped.lineage[0].lineage).is_length(1)
    assert_that(mapped.lineage[0].lineage[0].rev).is_equal_to("a" * 40)
    local = next(
        item for item in inventory.capabilities if item.id.package.publisher == "z"
    )
    assert_that(local.lineage[0].lineage[0].rev).is_none()


def test_deeper_reexport_appends_each_publisher_at_its_own_pin(
    provenance_repo: Path,
) -> None:
    """A further manifest publisher cannot hide ancestry behind nested exports."""
    root = provenance_repo
    extra = root / "w"
    extra.mkdir()
    (extra / "ai-skills.yaml").write_text(
        dump_document(
            {
                "apiVersion": "ai-skills.dev/v1",
                "publisher": {"id": "w", "repo": "fixture/w"},
                "vendors": [{"id": "y", "repo": "fixture/y", "sha": "b" * 40}],
                "exports": ["y/tools", "x/tools"],
            }
        )
    )
    path = root / "z/ai-skills.yaml"
    document = read_document(path)
    document["vendors"] = [{"id": "w", "repo": "fixture/w", "sha": "c" * 40}]
    path.write_text(dump_document(document))
    result = load_selection(
        root / "z", vendor_roots={"w": extra, "w/y": root / "y", "w/y/x": root / "x"}
    )
    assert_that(result.valid).is_false()
    cap = next(
        item for item in result.capabilities if item.id == "y/tools:skill/transformed"
    )
    assert_that(cap.state).is_equal_to("denied")
    assert_that([hop.origin for hop in cap.lineage[0].lineage]).is_equal_to(
        ["github.com/fixture/x", "github.com/fixture/y", "github.com/fixture/w"]
    )
    assert_that([hop.rev for hop in cap.lineage[0].lineage]).is_equal_to(
        ["a" * 40, "b" * 40, "c" * 40]
    )


def test_index_cannot_erase_recursively_known_resource_ancestry(
    provenance_repo: Path,
) -> None:
    """An authenticated current hop alone cannot erase a known resource's origin."""
    root = provenance_repo
    path = root / "y/ai-skills.lineage.json"
    records = json.loads(path.read_text())
    resource = next(item for item in records if item["id"] == "x/tools:resource/script")
    resource["lineage"] = resource["lineage"][-1:]
    path.write_text(json.dumps(records))
    result = load_selection(root / "z", vendor_roots=vendor_roots(root))
    assert_that(result.valid).is_false()
    assert_that(result.resources[0].state).is_equal_to("denied")
    assert_that(
        {hop.origin for chain in result.resources[0].lineage for hop in chain.lineage}
    ).contains("github.com/fixture/x", "github.com/fixture/y")
