"""Retain structural, unresolved-edge and payload evidence at recursive boundaries."""

from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest
from assertpy import assert_that

from ai_skills_engine.inventory.load import load_inventory
from ai_skills_engine.inventory.model import Capability, Inventory, Resource
from ai_skills_engine.inventory.unresolved_edge import UnresolvedEdge
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import load_consumer, read_document
from ai_skills_engine.manifest.vendor import Vendor
from ai_skills_engine.provenance.edges import bind_exports
from ai_skills_engine.provenance.exports import merge_imports


@pytest.mark.parametrize(
    "vendors",
    [None, [None], [{}], [{"id": 7}]],
    ids=["null-list", "null-record", "missing-id", "invalid-id"],
)
def test_imported_vendor_structure_is_validated_before_traversal(
    provenance_repo: Path, vendors: object
) -> None:
    """Malformed nested declarations produce schema errors instead of raw crashes."""
    root = provenance_repo
    path = root / "y/ai-skills.yaml"
    document = read_document(path)
    document["vendors"] = vendors
    path.write_text(dump_document(document))
    with pytest.raises(ValueError, match="schema.*vendors"):
        load_consumer(root / "z/ai-skills.yaml", vendor_roots={"y": root / "y"})


@pytest.mark.parametrize("field", ["requires", "related"])
def test_resolving_capability_edge_preserves_unresolved_resource_diagnostic(
    provenance_repo: Path, field: Literal["requires", "related"]
) -> None:
    """Equal selectors in different fields cannot clear each other's failures."""
    cap = load_inventory(provenance_repo / "x").capabilities[0]
    edges = (
        UnresolvedEdge(source=cap.id, field=field, target="*"),
        UnresolvedEdge(source=cap.id, field="resources", target="*"),
    )
    inventory = Inventory(
        capabilities=(cap,),
        resources=(),
        diagnostics=tuple(
            Diagnostic(
                f"inventory.unknown-{edge.field}",
                str(cap.id),
                f"Unknown declared {edge.field}: *",
            )
            for edge in edges
        ),
        unresolved_edges=edges,
    )
    result = bind_exports(inventory)
    assert_that(result.unresolved_edges).is_equal_to((edges[1],))
    assert_that([item.code for item in result.diagnostics]).is_equal_to(
        ["inventory.unknown-resources"]
    )
    assert_that(getattr(result.capabilities[0], field)).contains(cap.id)


@pytest.mark.parametrize("kind", ["capability", "resource"])
@pytest.mark.parametrize("changed", [False, True], ids=["same-bytes", "changed-bytes"])
@pytest.mark.parametrize("reverse", [False, True], ids=["forward", "reverse"])
def test_duplicate_exports_only_union_compatible_payloads(
    provenance_repo: Path, kind: str, changed: bool, reverse: bool
) -> None:
    """Same-origin revisions keep both chains only when their observed bytes agree."""
    inventory = load_inventory(provenance_repo / "x")
    if kind == "capability":
        _check_duplicate_exports(
            record=inventory.capabilities[0], changed=changed, reverse=reverse
        )
    else:
        _check_duplicate_exports(
            record=inventory.resources[0], changed=changed, reverse=reverse
        )


def _check_duplicate_exports[Record: (Capability, Resource)](
    *, record: Record, changed: bool, reverse: bool
) -> None:
    """Exercise both record types without erasing their generic merge contract.

    Args:
        record: Observed capability or resource payload.
        changed: Whether the incoming pin has incompatible payload bytes.
        reverse: Whether to reverse the order of the two input pins.
    """
    first = replace(
        record,
        lineage=(
            replace(
                record.lineage[0],
                lineage=(replace(record.lineage[0].lineage[0], rev="a" * 40),),
            ),
        ),
    )
    payload = (
        (replace(record.payload[0], sha256="f" * 64), *record.payload[1:])
        if changed
        else record.payload
    )
    second = replace(
        record,
        payload=payload,
        tree_digest="f" * 64 if changed else record.tree_digest,
        lineage=(
            replace(
                record.lineage[0],
                lineage=(
                    replace(
                        record.lineage[0].lineage[0],
                        rev="b" * 40,
                        tree_digest=(
                            "sha256:" + "f" * 64
                            if changed
                            else record.lineage[0].lineage[0].tree_digest
                        ),
                    ),
                ),
            ),
        ),
    )
    if reverse:
        first, second = second, first
    key = str(record.id)
    table = {key: first}
    findings: list[Diagnostic] = []
    merged = merge_imports(
        table=table,
        records=(second,),
        publisher="x",
        exports={"x/tools"},
        vendor=Vendor(id="x", repo="fixture/x", sha="b" * 40),
        findings=findings,
        selection_candidates=False,
    )
    if changed:
        assert_that([item.code for item in findings]).is_equal_to(
            ["inventory.duplicate-id"]
        )
        assert_that(table[key]).is_equal_to(first)
        assert_that(merged).is_empty()
    else:
        assert_that(findings).is_empty()
        assert_that(table[key].lineage).is_length(2)
        assert_that(table[key].payload).is_equal_to(record.payload)
        assert_that(merged).is_equal_to({key})
