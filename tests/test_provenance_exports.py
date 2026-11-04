"""Repeated exports retain coherent payload, ancestry and dependency evidence."""

from dataclasses import replace
from pathlib import Path

import pytest
from assertpy import assert_that
from provenance_export_helpers import diamond_exports, materialized_exports
from provenance_helpers import change_policy, vendor_roots

from ai_skills_engine import cli
from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.load import load_inventory
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.provenance.context import Context
from ai_skills_engine.provenance.exports import publish_exports
from ai_skills_engine.provenance.ingest import ingest
from ai_skills_engine.selection.load import load_selection


@pytest.mark.parametrize("kind", ["capability", "resource"])
@pytest.mark.parametrize("changed", [False, True], ids=["compatible", "incompatible"])
@pytest.mark.parametrize("reverse", [False, True], ids=["forward", "reverse"])
@pytest.mark.parametrize("strict", [False, True], ids=["warn", "strict"])
def test_materializations_are_validated_before_record_changes(
    provenance_repo: Path, kind: str, changed: bool, reverse: bool, strict: bool
) -> None:
    """Conflicts retain the original record; equal copies choose a stable path."""
    root = provenance_repo
    materialized_exports(root=root, kind=kind, changed=changed, reverse=reverse)
    inventory = load_inventory(root / "x")
    if kind == "capability":
        _check_materializations(
            original=inventory.capabilities[0],
            root=root,
            changed=changed,
            strict=strict,
        )
    else:
        _check_materializations(
            original=inventory.resources[0], root=root, changed=changed, strict=strict
        )


def _check_materializations[Record: (Capability, Resource)](
    *, original: Record, root: Path, changed: bool, strict: bool
) -> None:
    """Check the same publication contract while preserving each concrete record type.

    Args:
        original: Original pinned record.
        root: Fixture publication snapshots.
        changed: Whether incompatible claims must be rejected.
        strict: Final consumer policy strictness.
    """
    identity = str(original.id)
    original = replace(
        original,
        lineage=tuple(
            replace(chain, lineage=(replace(chain.lineage[0], rev="a" * 40),))
            for chain in original.lineage
        ),
    )
    table = {identity: original}
    context = Context(origin="github.com/fixture/y", rev="b" * 40, policy=None)
    findings: list[Diagnostic] = []
    publish_exports(
        table=table,
        root=root / "y",
        publisher="y",
        exports={"x/tools"},
        context=context,
        declared=ingest(root=root / "y", context=context),
        findings=findings,
        strict=strict,
        vendors=(),
    )
    result = table[identity]
    if changed:
        assert_that(result).is_equal_to(original)
        assert_that([d.code for d in findings]).is_equal_to(
            ["provenance.unverifiable-lineage"]
        )
        assert_that(findings[0].warning).is_equal_to(not strict)
    else:
        assert_that(findings).is_empty()
        assert_that(str(result.source_path)).is_equal_to("copy-a")
        assert_that({chain.lineage[-1].path for chain in result.lineage}).is_equal_to(
            {"copy-a", "copy-b"}
        )
        assert_that(
            {chain.lineage[-1].tree_digest for chain in result.lineage}
        ).is_equal_to({"sha256:" + result.tree_digest})
        assert_that({chain.lineage[0] for chain in result.lineage}).is_equal_to(
            {original.lineage[0].lineage[0]}
        )


@pytest.mark.parametrize("kind", ["capability", "resource"])
@pytest.mark.parametrize("damage", ["missing", "changed"])
@pytest.mark.parametrize("strict", [False, True])
def test_one_bad_materialization_prevents_all_record_changes(
    provenance_repo: Path, kind: str, damage: str, strict: bool
) -> None:
    """A valid sibling cannot authorize partial mutation when another claim fails."""
    root = provenance_repo
    materialized_exports(root=root, kind=kind, changed=False, reverse=False)
    file = next(path for path in (root / "y/copy-b").rglob("*") if path.is_file())
    if damage == "missing":
        file.unlink()
    else:
        file.write_text(file.read_text() + "Tampered.\n")
    inventory = load_inventory(root / "x")
    if kind == "capability":
        _check_materializations(
            original=inventory.capabilities[0], root=root, changed=True, strict=strict
        )
    else:
        _check_materializations(
            original=inventory.resources[0], root=root, changed=True, strict=strict
        )


@pytest.mark.parametrize("kind", ["capability", "resource"])
@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_materializations_reach_inventory_and_plan(
    provenance_repo: Path, capsys: pytest.CaptureFixture[str], kind: str, reverse: bool
) -> None:
    """The production recursive loader surfaces conflicts to the public plan command."""
    root = provenance_repo
    identity = materialized_exports(root=root, kind=kind, changed=True, reverse=reverse)
    change_policy(root=root / "z")
    inventory = load_inventory(root / "z", vendor_roots=vendor_roots(root))
    assert_that(
        [
            d.location
            for d in inventory.diagnostics
            if d.code == "provenance.unverifiable-lineage"
        ]
    ).contains(identity)
    assert_that(
        cli.main(
            [
                "plan",
                "--json",
                "--repo-root",
                str(root / "z"),
                "--vendor-root",
                f"y={root / 'y'}",
                "--vendor-root",
                f"y/x={root / 'x'}",
            ]
        )
    ).is_equal_to(1)
    assert_that(capsys.readouterr().out).contains(
        "provenance.unverifiable-lineage", identity
    )


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("denied", ["a", "b"])
def test_diamond_imports_retain_all_edges_and_resource_vetoes(
    tmp_path: Path, reverse: bool, denied: str
) -> None:
    """A resource deny on either input invalidates the same requiring capability."""
    roots = diamond_exports(root=tmp_path, reverse=reverse)
    inventory = load_inventory(tmp_path / "z", vendor_roots=roots)
    cap = next(c for c in inventory.capabilities if str(c.id) == "x/tools:skill/plain")
    for field, expected in (
        ("requires", {"x/tools:skill/dep-a", "x/tools:skill/dep-b"}),
        ("related", {"x/tools:skill/related-a", "x/tools:skill/related-b"}),
        ("resources", {"a/tools:resource/data", "b/tools:resource/data"}),
    ):
        assert_that({str(value) for value in getattr(cap, field)}).is_equal_to(expected)
    assert_that(cap.lineage).is_length(2)
    assert_that(load_selection(tmp_path / "z", vendor_roots=roots).valid).is_true()
    change_policy(root=tmp_path / "z", deny=(f"github.com/fixture/{denied}",))
    result = load_selection(tmp_path / "z", vendor_roots=roots)
    assert_that(result.valid).is_false()
    assert_that(
        [
            d.location
            for d in result.diagnostics
            if d.code == "selection.required-denied"
        ]
    ).contains(str(cap.id))


@pytest.mark.parametrize("reverse", [False, True])
def test_diamond_imports_retain_both_unresolved_declarations(
    tmp_path: Path, reverse: bool
) -> None:
    """Later recursive inputs cannot clear earlier inputs' unresolved-edge evidence."""
    roots = diamond_exports(root=tmp_path, reverse=reverse, missing=True)
    inventory = load_inventory(tmp_path / "z", vendor_roots=roots)
    assert_that(
        {
            e.target
            for e in inventory.unresolved_edges
            if str(e.source) == "x/tools:skill/plain"
        }
    ).is_equal_to({"x/tools:skill/missing-a", "x/tools:skill/missing-b"})
    messages = "\n".join(
        d.message
        for d in inventory.diagnostics
        if d.code == "inventory.unknown-requires"
    )
    assert_that(messages).contains("missing-a", "missing-b")
