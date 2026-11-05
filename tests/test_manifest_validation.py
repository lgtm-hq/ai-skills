"""Exercise real schema, typed loading, semantic checks and CLI diagnostics."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import get_args

import pytest
from assertpy import assert_that
from jsonschema import Draft202012Validator

from ai_skills_engine import cli
from ai_skills_engine.manifest import identity
from ai_skills_engine.manifest.codec import encode, field_key
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import load_manifest, read_document
from ai_skills_engine.manifest.validate import schema_path, validate_document
from ai_skills_engine.registry.registry import load_unique_yaml_text

FIXTURES = Path(__file__).parent / "fixtures" / "manifest"


@pytest.fixture
def manifest_repo(tmp_path: Path) -> Path:
    """Create an author root with a complete positive declaration fixture.

    Args:
        tmp_path: Isolated fixture repository.

    Returns:
        Root containing the positive manifest.
    """
    (tmp_path / "ai-skills.yaml").write_bytes((FIXTURES / "valid.yaml").read_bytes())
    return tmp_path


def test_schema_model_and_positive_fixture_agree(manifest_repo: Path) -> None:
    """Load all named fields as typed immutable records and validate re-encoding."""
    schema = json.loads(schema_path().read_text())
    Draft202012Validator.check_schema(schema)
    path = manifest_repo / "ai-skills.yaml"
    model = load_manifest(path)
    assert_that(validate_document(encode(model))).is_empty()
    assert_that(
        model.vendors[0].mapping.packages[0].capabilities["help"].id
    ).is_equal_to("helper")
    assert_that(model.vendors[0].include).is_equal_to(("upstream/tools*",))
    assert_that(model.vendors[0].exclude).is_equal_to(())
    with pytest.raises(FrozenInstanceError):
        model.publisher.id = "changed"
    with pytest.raises(TypeError):
        model.extensions["x-other"] = True
    with pytest.raises(TypeError):
        model.extensions["x-example"]["opaque"][1]["arbitrary"] = False
    assert_that(set(schema["$defs"]["role"]["enum"])).is_equal_to(set(identity.Role))
    assert_that(set(schema["$defs"]["mode"]["enum"])).is_equal_to(
        set(get_args(identity.Mode.__value__))
    )
    assert_that(set(schema["$defs"]["transport"]["enum"])).is_equal_to(
        set(get_args(identity.Transport.__value__))
    )
    assert_that(schema["$id"]).starts_with("https://")


def test_every_record_matches_its_closed_schema(manifest_repo: Path) -> None:
    """Recursively compare loaded record fields with the corresponding schema."""
    schema = json.loads(schema_path().read_text())
    model = load_manifest(manifest_repo / "ai-skills.yaml")
    records = {
        "publisher": model.publisher,
        "package": model.packages[0],
        "capability": model.packages[0].capabilities[0],
        "resource": model.packages[0].resources[0],
        "vendor": model.vendors[0],
        "mapping": model.vendors[0].mapping,
        "mappedPackage": model.vendors[0].mapping.packages[0],
        "mappedCapability": model.vendors[0].mapping.packages[0].capabilities["help"],
        "policy": model.policy,
        "provenance": model.policy.provenance,
        "deny": model.policy.deny,
        "overrides": model.overrides,
        "migration": model.overrides.migrations[0],
        "attestation": model.overrides.attestations[0],
        "collision": model.overrides.collisions[0],
    }
    for name, record in records.items():
        definition = schema["$defs"][name]
        assert_that(
            {
                field_key(item.name)
                for item in fields(record)
                if item.name != "extensions"
            }
        ).described_as(name).is_equal_to(set(definition["properties"]))
        assert_that(definition["additionalProperties"]).is_false()
        assert_that(set(definition["patternProperties"])).is_equal_to({"^x-"})
    assert_that(
        {field_key(item.name) for item in fields(model) if item.name != "extensions"}
    ).is_equal_to(set(schema["properties"]))


@pytest.mark.parametrize(
    ("fixture", "code"),
    [
        ("unknown-version", "schema"),
        ("missing-capability-id", "schema"),
        ("bad-sha", "schema"),
        ("duplicate-package", "duplicate-id"),
        ("duplicate-capability", "duplicate-id"),
        ("duplicate-resource", "duplicate-id"),
        ("duplicate-vendor", "duplicate-id"),
        ("duplicate-mapped-package", "duplicate-id"),
        ("dangling-export", "dangling-export"),
        ("file-selector", "invalid-selector"),
        ("middle-wildcard", "invalid-selector"),
        ("bad-requires", "invalid-selector"),
        ("bad-related", "invalid-selector"),
        ("bad-resource-reference", "invalid-selector"),
        ("bad-mapping-capability", "invalid-selector"),
        ("unknown-nested-key", "schema"),
        ("bad-role", "schema"),
        ("bad-mode", "schema"),
        ("bad-transport", "schema"),
        ("extension-does-not-open-object", "schema"),
    ],
)
def test_negative_fixture_and_cli(
    fixture: str,
    code: str,
    manifest_repo: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The same invalid input fails both the real loader and production CLI."""
    path = manifest_repo / "ai-skills.yaml"
    path.write_bytes((FIXTURES / f"{fixture}.yaml").read_bytes())
    # Schema diagnostics inspect decoded data; the real loader also enforces
    # source spelling before constructing its model (including bad SHA literals).
    findings = validate_document(load_unique_yaml_text(text=path.read_text()))
    assert_that([item.code for item in findings]).contains(code)
    assert_that(
        all(item.location.startswith("/") and item.message for item in findings)
    ).is_true()
    with pytest.raises(ValueError):
        load_manifest(path)
    assert_that(
        cli.main(["--repo-root", str(manifest_repo), "manifest", "validate"])
    ).is_equal_to(1)
    assert_that(capsys.readouterr().out).contains(code)


@pytest.mark.parametrize(
    "value",
    [
        "owner/tools",
        "owner/tool*",
        "owner/*",
        "owner/tools:skill/help",
        "owner/tools:resource/*",
        "owner/tools:integration/start*",
    ],
)
def test_selector_syntax_accepts_contract(value: str) -> None:
    """Only the last identity segment may contain a trailing wildcard."""
    assert_that(identity.parse_id(value, selector=True)[0]).is_equal_to("owner")


@pytest.mark.parametrize(
    "value",
    [
        "tools",
        "./skills/run",
        "/skills/run",
        "owner/tools/SKILL.md",
        "owner*/tools",
        "owner/tools:*/run",
        "owner/tools:skill/a*b",
        "owner/tools:agent/run",
        "owner//tools",
        "owner/tools:skill/../run",
    ],
)
def test_selector_syntax_rejects_paths_and_bad_roles(value: str) -> None:
    """Filesystem and glob syntax cannot masquerade as stable IDs."""
    with pytest.raises(ValueError):
        identity.parse_id(value, selector=True)


@pytest.mark.parametrize(
    "fragment",
    [
        "apiVersion: ai-skills.dev/v1\napiVersion: ai-skills.dev/v2\n",
        "publisher: {id: local, id: attacker}\n",
    ],
)
def test_duplicate_yaml_keys_rejected(tmp_path: Path, fragment: str) -> None:
    """The production loader retains duplicate protection at every depth."""
    path = tmp_path / "ai-skills.yaml"
    path.write_text(fragment)
    with pytest.raises(ValueError, match="duplicate key"):
        read_document(path)


def test_nested_extensions_do_not_admit_typos(manifest_repo: Path) -> None:
    """An allowed x-* key never opens arbitrary sibling properties."""
    path = manifest_repo / "ai-skills.yaml"
    data = read_document(path)
    data["packages"][0]["x-notes"] = {"any": "payload"}
    assert_that(validate_document(data)).is_empty()
    data["packages"][0]["typo"] = True
    assert_that([item.code for item in validate_document(data)]).contains("schema")
    path.write_text(dump_document(data))


@pytest.mark.parametrize(
    "extension", ["{1: numeric-key}", "2026-11-02", ".nan", "&loop [*loop]"]
)
def test_yaml_extensions_remain_json_values(tmp_path: Path, extension: str) -> None:
    """Opaque extensions cannot bypass the JSON data model or create cycles."""
    path = tmp_path / "ai-skills.yaml"
    path.write_text(
        f"apiVersion: ai-skills.dev/v1\npublisher: {{id: local}}\nx-data: {extension}\n"
    )
    assert_that(
        [item.code for item in validate_document(read_document(path))]
    ).contains("schema")


@pytest.mark.parametrize(
    ("field", "value"),
    [("id", "vendor\n"), ("repo", "owner/repo\n"), ("sha", "a" * 40 + "\n")],
)
def test_schema_patterns_use_ecma_end_anchors(
    manifest_repo: Path, field: str, value: str
) -> None:
    """A trailing newline never satisfies a ``$``-anchored schema pattern."""
    data = read_document(manifest_repo / "ai-skills.yaml")
    assert_that(validate_document(data)).is_empty()
    data["vendors"][0][field] = value
    locations = {item.location for item in validate_document(data)}
    assert_that(locations).contains(f"/vendors/0/{field}")


def test_rename_collision_without_name_is_rejected(manifest_repo: Path) -> None:
    """A rename collision override must name its new destination."""
    data = read_document(manifest_repo / "ai-skills.yaml")
    collision = data["overrides"]["collisions"][0]
    assert_that(collision["action"]).is_equal_to("rename")
    del collision["name"]
    codes = {(item.code, item.location) for item in validate_document(data)}
    assert_that(codes).contains(("schema", "/overrides/collisions/0"))
