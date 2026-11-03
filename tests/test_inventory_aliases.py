"""Skill destination aliases never rename specialists or other capability roles."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from assertpy import assert_that
from inventory_helpers import configure_inventory_aliases, inventory_snapshot

from ai_skills_engine import cli
from ai_skills_engine.inventory import load_inventory
from ai_skills_engine.inventory.capability_id import CapabilityId
from ai_skills_engine.inventory.collect import collect_package
from ai_skills_engine.inventory.package_id import PackageId
from ai_skills_engine.inventory.pending import PendingCapability
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.inventory.resource_record import Resource
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.identity import Role
from ai_skills_engine.manifest.load import load_consumer, read_document

pytest_plugins = ["inventory_helpers"]


@pytest.mark.parametrize("control", ["same-stem", "ordinary"])
def test_skill_aliases_preserve_other_roles_and_stable_ids(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    control: str,
) -> None:
    """Aliases preserve payloads, roles and IDs, while recording their transforms."""
    root, vendor = inventory_repo
    configure_inventory_aliases(root=root, vendor=vendor, control=control)
    path = root / "ai-skills.yaml"
    document = read_document(path)
    package = document["vendors"][0]["mapping"]["packages"][0]
    aliases = package.pop("renameSkills")
    path.write_text(dump_document(document))
    baseline = load_inventory(root, vendor_roots={"vendor": vendor})
    originals = {item.id: item for item in baseline.capabilities}
    package["renameSkills"] = aliases
    path.write_text(dump_document(document))
    before = inventory_snapshot(root, vendor)
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([item for item in result.diagnostics if not item.warning]).is_empty()
    assert_that([item.id for item in result.capabilities]).is_equal_to(list(originals))
    expected = {"vendor/tools:skill/helper": (aliases["help"],)}
    if control == "same-stem":
        expected["vendor/tools:skill/reviewer"] = ("review-helper",)
    for item in result.capabilities:
        assert_that(item.id).is_instance_of(CapabilityId)
        assert_that(item.aliases).described_as(str(item.id)).is_equal_to(
            expected.get(str(item.id), ())
        )
        ancestry = tuple(
            replace(
                chain,
                lineage=tuple(
                    replace(
                        hop,
                        transforms=tuple(
                            transform
                            for transform in hop.transforms
                            if transform != "alias"
                        ),
                    )
                    for hop in chain.lineage
                ),
            )
            for chain in item.lineage
        )
        assert_that(replace(item, aliases=(), lineage=ancestry)).is_equal_to(
            originals[item.id]
        )
        assert_that(
            any(
                "alias" in hop.transforms
                for chain in item.lineage
                for hop in chain.lineage
            )
        ).is_equal_to(bool(item.aliases))
    args = ["--repo-root", str(root), "--vendor-root", f"vendor={vendor}"]
    for _ in range(2):
        assert_that(cli.main(["inventory", "--json", *args])).is_zero()
        assert_that(capsys.readouterr().out).is_equal_to(result.to_json())
    assert_that(cli.main(["manifest", "validate", *args])).is_zero()
    capsys.readouterr()
    assert_that(inventory_snapshot(root, vendor)).is_equal_to(before)


@pytest.mark.parametrize(
    "control,key", [("specialist-only", "reviewer"), ("unused", "absent")]
)
def test_rename_key_requires_a_selected_skill(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    control: str,
    key: str,
) -> None:
    """A specialist name cannot make an otherwise unused renameSkills key valid."""
    root, vendor = inventory_repo
    configure_inventory_aliases(root=root, vendor=vendor, control=control)
    before = inventory_snapshot(root, vendor)
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    errors = [item for item in result.diagnostics if not item.warning]
    assert_that(
        [item.message for item in errors if item.code == "inventory.invalid-payload"]
    ).is_equal_to([f"Unused mapped capability/renameSkills: ['{key}']"])
    args = ["--repo-root", str(root), "--vendor-root", f"vendor={vendor}"]
    assert_that(cli.main(["inventory", "--json", *args])).is_equal_to(1)
    assert_that(json.loads(capsys.readouterr().out)).is_equal_to(
        json.loads(result.to_json())
    )
    assert_that(cli.main(["manifest", "validate", *args])).is_equal_to(1)
    assert_that(capsys.readouterr().out).contains("inventory.invalid-payload", key)
    assert_that(inventory_snapshot(root, vendor)).is_equal_to(before)


def test_collection_applies_aliases_only_to_skill_roles(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Even aliases matching every payload stem cannot leak into the other roles."""
    root, vendor = inventory_repo
    manifest, _, _ = load_consumer(
        root / "ai-skills.yaml", vendor_roots={"vendor": vendor}
    )
    package = manifest.packages[0]
    aliases = {
        (
            Path(item.path).stem
            if (root / item.path).is_file()
            else Path(item.path).name
        ): f"alias-{item.id}"
        for item in package.capabilities
    }
    pending: list[PendingCapability] = []
    resources: list[Resource] = []
    resource_paths: dict[ResourceId, Path] = {}
    diagnostics: list[Diagnostic] = []
    rejected: list[CapabilityId | ResourceId] = []
    before = inventory_snapshot(root, vendor)
    collect_package(
        root=root,
        package=package,
        package_id=PackageId(publisher=manifest.publisher.id, name=package.id),
        origin="github.com/fixture/catalog",
        aliases=aliases,
        vendor=None,
        pending=pending,
        resources=resources,
        resource_paths=resource_paths,
        diagnostics=diagnostics,
        rejected=rejected,
    )
    assert_that(rejected).is_empty()
    assert_that([item for item in diagnostics if not item.warning]).is_empty()
    assert_that({item.capability.role for item in pending}).is_equal_to(set(Role))
    for item in pending:
        capability = item.capability
        assert_that(capability.aliases).described_as(str(capability.id)).is_equal_to(
            (f"alias-{capability.id.name}",) if capability.role == Role.SKILL else ()
        )
    assert_that(inventory_snapshot(root, vendor)).is_equal_to(before)


def test_specialist_declarations_remain_valid_without_a_skill(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Capability declarations still accept specialist names independently of skills."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    package = document["vendors"][0]["mapping"]["packages"][0]
    package["capabilities"]["reviewer"] = {"id": "stable-specialist"}
    (root / "ai-skills.yaml").write_text(dump_document(document))
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([item for item in result.diagnostics if not item.warning]).is_empty()
    specialist = next(
        item for item in result.capabilities if item.id.name == "stable-specialist"
    )
    assert_that(str(specialist.id)).is_equal_to(
        "vendor/tools:specialist/stable-specialist"
    )
    assert_that(specialist.aliases).is_empty()
