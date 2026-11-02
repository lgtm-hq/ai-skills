"""Vendor authority, pins, filters and explicit identity migration regressions."""

import json
import shutil
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.bake import vendor_plugins
from ai_skills_engine.inventory import load_inventory
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.registry.vendor import Vendor

pytest_plugins = ["inventory_helpers"]


def test_manifest_vendor_uses_its_publisher_and_ignores_authority(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Imported authority cannot change consumer policy or certify host semantics."""
    root, vendor = inventory_repo
    path = root / "ai-skills.yaml"
    document = read_document(path)
    document["vendors"][0].pop("mapping")
    document["exports"] = ["tools", "actual/tools"]
    document["packages"][0]["capabilities"][0]["requires"] = ["actual/tools:skill/help"]
    document["policy"] = {"provenance": {"mode": "strict", "acceptAttestations": False}}
    path.write_text(dump_document(document))
    (vendor / "ai-skills.yaml").write_text(
        dump_document(
            {
                "apiVersion": "ai-skills.dev/v1",
                "publisher": {"id": "actual"},
                "packages": [
                    {
                        "id": "tools",
                        "capabilities": [{"id": "help", "path": "skills/help"}],
                        "resources": [],
                    }
                ],
                "policy": {"provenance": {"mode": "warn", "acceptAttestations": True}},
                "overrides": {
                    "migrations": [
                        {
                            "from": "fixture/tools:skill/stable",
                            "to": "actual/tools:skill/help",
                        }
                    ]
                },
                "x-trust": {"execute": "skills/help/danger.py"},
            }
        )
    )
    # A real vendor manifest must declare its own resources; mapping authority
    # cannot survive when that manifest takes precedence.
    (vendor / "skills/help/SKILL.md").write_text(
        "---\nname: help\ndescription: Helper.\ndisable-model-invocation: true\n---\n"
    )
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([item for item in result.diagnostics if not item.warning]).is_empty()
    assert_that(
        [item.code for item in result.diagnostics].count("vendor-authority-ignored")
    ).is_equal_to(3)
    helper = next(
        item for item in result.capabilities if item.id.package.publisher == "actual"
    )
    assert_that(str(helper.id)).is_equal_to("actual/tools:skill/help")
    assert_that(helper.host_attributes[0].rule_for("codex", strict=False)).is_equal_to(
        "unverified"
    )
    assert_that(helper.host_attributes[0].rule_for("codex")).is_equal_to("refuse")
    assert_that(read_document(path)["policy"]).is_equal_to(document["policy"])


def test_manifestless_rename_changes_id_and_migration_preserves_references(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Stem identity changes unless declared; explicit migration maps old references."""
    root, vendor = inventory_repo
    path = root / "ai-skills.yaml"
    document = read_document(path)
    mapped = document["vendors"][0]["mapping"]["packages"][0]
    mapped.pop("capabilities")
    document["packages"][0]["capabilities"][0]["requires"] = ["vendor/tools:skill/help"]
    path.write_text(dump_document(document))
    before = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([str(item.id) for item in before.capabilities]).contains(
        "vendor/tools:skill/help"
    )
    (vendor / "skills/help").rename(vendor / "skills/renamed")
    mapped["renameSkills"] = {"renamed": "help-alias"}
    path.write_text(dump_document(document))
    after = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([str(item.id) for item in after.capabilities]).contains(
        "vendor/tools:skill/renamed"
    ).does_not_contain("vendor/tools:skill/help")
    assert_that([item.code for item in after.diagnostics]).contains(
        "inventory.unknown-requires"
    )
    document["overrides"] = {
        "migrations": [
            {"from": "vendor/tools:skill/help", "to": "vendor/tools:skill/renamed"}
        ]
    }
    path.write_text(dump_document(document))
    migrated = load_inventory(root, vendor_roots={"vendor": vendor})
    start = next(item for item in migrated.capabilities if item.id.name == "stable")
    assert_that([str(item) for item in start.requires]).is_equal_to(
        ["vendor/tools:skill/renamed"]
    )


def test_declared_wildcards_and_direct_import_filters(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Selectors resolve only declarations and never pull excluded dependencies in."""
    root, vendor = inventory_repo
    path = root / "ai-skills.yaml"
    document = read_document(path)
    document["packages"][0]["capabilities"][0]["related"] = [
        "vendor/tools:specialist/*"
    ]
    document["vendors"][0]["include"] = ["vendor/tools*"]
    path.write_text(dump_document(document))
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    start = next(item for item in result.capabilities if item.id.name == "stable")
    assert_that([str(item) for item in start.related]).is_equal_to(
        ["vendor/tools:specialist/reviewer"]
    )
    document["vendors"][0]["exclude"] = ["vendor/tools:skill/helper"]
    path.write_text(dump_document(document))
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([str(item.id) for item in result.capabilities]).does_not_contain(
        "vendor/tools:skill/helper"
    )
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.unknown-requires"
    )
    document["vendors"][0]["include"] = []
    path.write_text(dump_document(document))
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that(
        [item for item in result.capabilities if item.id.package.publisher == "vendor"]
    ).is_empty()


def test_explicit_fetch_uses_exact_pin_and_existing_bake_boundary(
    inventory_repo: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The only acquisition route is the existing fetcher with the declared SHA."""
    root, vendor = inventory_repo
    calls: list[tuple[str, str]] = []

    def fetch(*, vendor: Vendor, dest: Path) -> None:
        """Replace network acquisition with fixed fixture bytes."""
        calls.append((vendor.repo, vendor.sha))
        shutil.copytree(src=inventory_repo[1], dst=dest, symlinks=True)

    monkeypatch.setattr(vendor_plugins, "_fetch_vendor_tree", fetch)
    result = load_inventory(root, fetch_vendors=True)
    assert_that(calls).is_equal_to(
        [("upstream/tools", "0123456789abcdef0123456789abcdef01234567")]
    )
    assert_that([item for item in result.diagnostics if not item.warning]).is_empty()
    assert_that([item.code for item in result.diagnostics]).does_not_contain(
        "inventory.vendor-pin-unverified"
    )
    assert_that(
        next(item for item in result.capabilities if item.id.name == "stable")
        .host_attributes[0]
        .rule_for("cursor", strict=False)
    ).is_equal_to("unverified")
    calls.clear()
    load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that(calls).is_empty()


@pytest.mark.parametrize("argument", ["bad", "=path", "vendor=", "unknown=."])
def test_bad_vendor_root_is_cli_error(
    inventory_repo: tuple[Path, Path], capsys: pytest.CaptureFixture[str], argument: str
) -> None:
    """Bad roots fail visibly without fetching or falling back to author inputs."""
    root, _ = inventory_repo
    assert_that(
        cli.main(["inventory", "--repo-root", str(root), "--vendor-root", argument])
    ).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("inventory:")


def test_missing_vendor_input_is_visible_without_network(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Offline missing imports remain partial observations, with broken edges errors."""
    root, _ = inventory_repo
    result = load_inventory(root)
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.vendor-unavailable", "inventory.unknown-requires"
    )
    assert_that(
        next(
            item
            for item in result.diagnostics
            if item.code == "inventory.vendor-unavailable"
        ).warning
    ).is_true()


def test_duplicate_inventory_id_and_unused_mapping_are_errors(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Cross-publisher aliases and unused declaration typos cannot overwrite records."""
    root, vendor = inventory_repo
    path = root / "ai-skills.yaml"
    document = read_document(path)
    duplicate = dict(document["vendors"][0])
    duplicate["id"] = "other"
    duplicate.pop("mapping")
    document["vendors"].append(duplicate)
    path.write_text(dump_document(document))
    (vendor / "ai-skills.yaml").write_text(
        dump_document(
            {
                "apiVersion": "ai-skills.dev/v1",
                "publisher": {"id": "fixture"},
                "packages": [
                    {
                        "id": "tools",
                        "capabilities": [{"id": "stable", "path": "skills/help"}],
                    }
                ],
            }
        )
    )
    # Only the second alias supplies a manifest; its publisher collides with local.
    result = load_inventory(root, vendor_roots={"other": vendor})
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.duplicate-id"
    )
    (vendor / "ai-skills.yaml").unlink()
    document["vendors"].pop()
    document["vendors"][0]["mapping"]["packages"][0]["capabilities"]["typo"] = {}
    path.write_text(dump_document(document))
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.invalid-payload"
    )


def test_fetch_notes_do_not_corrupt_cli_json(
    inventory_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Shared fetcher notes stay visible on stderr, leaving parseable JSON stdout."""
    root, _vendor = inventory_repo

    def fetch(*, vendor: Vendor, dest: Path) -> None:
        """Supply fixture bytes with the existing fetcher's note behavior."""
        print("fixture acquisition note")
        shutil.copytree(src=inventory_repo[1], dst=dest, symlinks=True)

    monkeypatch.setattr(vendor_plugins, "_fetch_vendor_tree", fetch)
    assert_that(
        cli.main(["inventory", "--json", "--fetch-vendors", "--repo-root", str(root)])
    ).is_zero()
    result = capsys.readouterr()
    assert_that(json.loads(result.out)["capabilities"]).is_length(8)
    assert_that(result.err).contains("fixture acquisition note")


def test_roots_only_mapping_retains_stem_identity(
    inventory_repo: tuple[Path, Path],
) -> None:
    """A manifestless roots-only vendor gets the documented alias package identity."""
    root, vendor = inventory_repo
    path = root / "ai-skills.yaml"
    document = read_document(path)
    document["vendors"][0]["mapping"].pop("packages")
    document["exports"] = ["tools"]
    document["packages"][0]["capabilities"][0]["requires"] = [
        "vendor/vendor:skill/help"
    ]
    path.write_text(dump_document(document))
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    helper = next(
        item for item in result.capabilities if item.id.package.publisher == "vendor"
    )
    assert_that(str(helper.id)).is_equal_to("vendor/vendor:skill/help")
    assert_that(helper.aliases).is_empty()
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.undeclared-resource"
    )


@pytest.mark.parametrize(
    "origin", ["github.com/fixture/catalog", "https://example.test/catalog"]
)
def test_qualified_publisher_origin_is_preserved(
    inventory_repo: tuple[Path, Path], origin: str
) -> None:
    """Already qualified publisher origins must not gain a second GitHub prefix."""
    root, vendor = inventory_repo
    path = root / "ai-skills.yaml"
    document = read_document(path)
    document["publisher"]["repo"] = origin
    path.write_text(dump_document(document))
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that(
        {
            item.origin
            for item in result.capabilities
            if item.id.package.publisher == "fixture"
        }
    ).is_equal_to({origin})
