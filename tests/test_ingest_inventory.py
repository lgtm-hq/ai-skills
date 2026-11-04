"""Declaration-level ingestion evidence at actual inventory and plan boundaries."""

import json
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.inventory.capability_id import CapabilityId
from ai_skills_engine.inventory.load import load_inventory
from ai_skills_engine.inventory.pending import PendingCapability
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document

pytest_plugins = ["ingest_helpers", "inventory_helpers"]


def configure_selection(*, root: Path, bad: str, requirer: str, control: str) -> None:
    """Apply excludes to the rejected declaration and its known requirer.

    Args:
        root: Consumer repository.
        bad: Typed rejected target.
        requirer: Valid capability with a required edge to the target.
        control: Both excluded, retained, or required excluded target.
    """
    path = root / "ai-skills.yaml"
    document = read_document(path)
    document["vendors"][0]["exclude"] = (
        [bad, requirer]
        if control == "both-excluded"
        else [bad] if control == "required" else []
    )
    path.write_text(dump_document(document))


def test_inventory_clean_declaration_control(
    rejected_inventory: tuple[Path, Path, str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The resource and capability controls are otherwise valid publications."""
    root, source, bad, _ = rejected_inventory
    (source / "bad.md").write_text("Ordinary independent Markdown\n")
    inventory = load_inventory(root, vendor_roots={"vendor": source})
    assert_that(inventory.rejected).is_empty()
    assert_that([item for item in inventory.diagnostics if not item.warning]).is_empty()
    identities = [str(item.id) for item in inventory.resources] + [
        str(item.id) for item in inventory.capabilities
    ]
    assert_that(identities).contains(bad)
    for command in ("inventory", "plan"):
        assert_that(
            cli.main(
                [
                    command,
                    "--repo-root",
                    str(root),
                    "--vendor-root",
                    f"vendor={source}",
                    "--json",
                ]
            )
        ).is_zero()
        capsys.readouterr()


@pytest.mark.parametrize("failure", ["secret", "lfs", "symlink"])
def test_inventory_preserves_valid_declarations_and_typed_rejections(
    rejected_inventory: tuple[Path, Path, str, str],
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    """One secret payload cannot erase a safe resource, capability or edge source."""
    root, source, bad, requirer = rejected_inventory
    expected = "aws-access-key-id"
    if failure == "lfs":
        (source / "bad.md").write_bytes(
            b"version https://git-lfs.github.com/spec/v1\noid sha256:"
            + b"a" * 64
            + b"\nsize 123\n"
        )
        expected = "stored in Git LFS"
    elif failure == "symlink":
        (source / "bad.md").unlink()
        (source / "bad.md").symlink_to("valid.txt")
        expected = "symlink rejected"
    inventory = load_inventory(root, vendor_roots={"vendor": source})
    assert_that([str(item.id) for item in inventory.resources]).contains(
        "upstream/tools:resource/valid"
    )
    assert_that([str(item.id) for item in inventory.capabilities]).contains(
        "upstream/tools:skill/good", requirer
    )
    assert_that([str(item) for item in inventory.rejected]).is_equal_to([bad])
    assert_that(isinstance(inventory.rejected[0], ResourceId)).is_equal_to(
        ":resource/" in bad
    )
    assert_that(
        [
            (str(edge.source), edge.field, edge.target)
            for edge in inventory.unresolved_edges
        ]
    ).contains((requirer, "resources" if ":resource/" in bad else "requires", bad))
    assert_that(
        cli.main(
            [
                "inventory",
                "--repo-root",
                str(root),
                "--vendor-root",
                f"vendor={source}",
                "--json",
            ]
        )
    ).is_equal_to(1)
    output = capsys.readouterr()
    assert_that(output.out + output.err).contains(expected).does_not_contain(
        "AKIA" + "A" * 16
    )
    document = json.loads(output.out)
    assert_that(document["rejected"]).is_equal_to([bad])


@pytest.mark.parametrize("control", ["both-excluded", "retained", "required"])
def test_plan_scopes_rejected_ingestion_by_requirer(
    rejected_inventory: tuple[Path, Path, str, str],
    capsys: pytest.CaptureFixture[str],
    control: str,
) -> None:
    """Excluding both ends is safe; retained requirers retain accurate target errors."""
    root, source, bad, requirer = rejected_inventory
    configure_selection(root=root, bad=bad, requirer=requirer, control=control)
    expected = int(control != "both-excluded")
    assert_that(
        cli.main(
            [
                "plan",
                "--repo-root",
                str(root),
                "--vendor-root",
                f"vendor={source}",
                "--json",
            ]
        )
    ).is_equal_to(expected)
    output = capsys.readouterr()
    assert_that(output.out + output.err).does_not_contain("AKIA" + "A" * 16)
    document = json.loads(output.out)
    assert_that([item["id"] for item in document["capabilities"]]).contains(
        "upstream/tools:skill/good", requirer
    )
    if expected:
        code = (
            "selection.required-excluded"
            if control == "required"
            else "selection.required-missing"
        )
        findings = [
            item
            for item in document["diagnostics"]
            if item["code"] == code and item["location"] == bad
        ]
        assert_that(findings).is_length(1)
        assert_that(findings[0]["chain"]).is_equal_to(
            [bad]
            if control == "retained" and ":resource/" not in bad
            else [requirer, bad]
        )


@pytest.mark.parametrize("limit", ["pluginBytes", "archiveMembers"])
def test_package_budget_is_shared_across_independent_declarations(
    rejected_inventory: tuple[Path, Path, str, str],
    capsys: pytest.CaptureFixture[str],
    limit: str,
) -> None:
    """Per-declaration recovery cannot reset the package's byte or member budget."""
    root, source, _, _ = rejected_inventory
    (source / "bad.md").write_text("ordinary independent payload\n")
    path = root / "ai-skills.yaml"
    document = read_document(path)
    document["vendors"][0]["ingestLimits"] = {
        limit: 1 if limit == "archiveMembers" else 50,
        "reason": "Synthetic aggregate budget",
    }
    path.write_text(dump_document(document))
    # Direct collection isolates the selected package budget from the separate
    # whole-snapshot structural archive budget used by load_inventory.
    from ai_skills_engine.inventory.collect import collect_package
    from ai_skills_engine.inventory.package_id import PackageId
    from ai_skills_engine.manifest.load import load_consumer, load_manifest

    package = load_manifest(source / "ai-skills.yaml").packages[0]
    consumer, _, _ = load_consumer(path, vendor_roots={"vendor": source})
    pending: list[PendingCapability] = []
    resources: list[Resource] = []
    rejected: list[CapabilityId | ResourceId] = []
    diagnostics: list[Diagnostic] = []
    collect_package(
        root=source,
        package=package,
        package_id=PackageId.parse("upstream/tools"),
        origin="upstream/tools",
        aliases={},
        vendor=consumer.vendors[0],
        pending=pending,
        resources=resources,
        resource_paths={},
        rejected=rejected,
        diagnostics=diagnostics,
    )
    assert_that([str(item) for item in rejected]).is_not_empty()
    assert_that(" ".join(item.message for item in diagnostics)).contains(limit)
    assert_that([str(item.id) for item in resources]).contains(
        "upstream/tools:resource/valid"
    )
    capsys.readouterr()
