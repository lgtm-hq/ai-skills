"""Host YAML values retain capability identity, payload and declared edges."""

import hashlib
import json
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.inventory import load_inventory

pytest_plugins = ["inventory_helpers"]


@pytest.mark.parametrize("key", ["disable-model-invocation", "vendor-permission"])
@pytest.mark.parametrize(
    "yaml_value,normalized",
    [
        ("true", True),
        ('"restricted"', "restricted"),
        ("[false, text, 3, null]", [False, "text", 3, None]),
        (
            "[1.5, {2.5: float-key, null: null-key}]",
            [
                1.5,
                {"$yaml": "mapping", "items": [[2.5, "float-key"], [None, "null-key"]]},
            ],
        ),
        ("[&shared [true], *shared]", [[True], [True]]),
        ("2026-11-02", {"$yaml": "date", "value": "2026-11-02"}),
        (
            "2026-11-02T12:30:00Z",
            {"$yaml": "datetime", "value": "2026-11-02T12:30:00+00:00"},
        ),
        (
            "{1: first, '1': second, true: invalid}",
            None,
        ),
        (
            "{1: first, '1': second, two: {true: yes-value, 'true': string-value}}",
            {
                "$yaml": "mapping",
                "items": [
                    ["1", "second"],
                    [
                        "two",
                        {
                            "$yaml": "mapping",
                            "items": [["true", "string-value"], [True, "yes-value"]],
                        },
                    ],
                    [1, "first"],
                ],
            },
        ),
        (
            "{nested: [2026-11-02, {1: first, two: second}]}",
            {
                "nested": [
                    {"$yaml": "date", "value": "2026-11-02"},
                    {"$yaml": "mapping", "items": [["two", "second"], [1, "first"]]},
                ]
            },
        ),
        (
            "{'$yaml': date, value: literal}",
            {"$yaml": "mapping", "items": [["$yaml", "date"], ["value", "literal"]]},
        ),
    ],
    ids=[
        "bool",
        "string",
        "list",
        "float-null-keys",
        "shared-alias",
        "date",
        "datetime",
        "duplicate-yaml-key",
        "typed-keys",
        "nested",
        "reserved-key",
    ],
)
def test_host_values_through_loader_and_cli(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    key: str,
    yaml_value: str,
    normalized: object,
) -> None:
    """Supported values normalize losslessly; YAML duplicate keys still fail closed."""
    root, vendor = inventory_repo
    before = load_inventory(root, vendor_roots={"vendor": vendor})
    baseline = next(item for item in before.capabilities if item.id.name == "stable")
    path = root / "skills/start/SKILL.md"
    path.write_text(
        path.read_text().replace(
            "disable-model-invocation: true", f"{key}: {yaml_value}"
        )
    )
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    if normalized is None:
        assert_that([item.code for item in result.diagnostics]).contains(
            "inventory.invalid-payload"
        )
        return
    start = next(item for item in result.capabilities if item.id.name == "stable")
    assert_that((start.id, start.requires, start.related, start.resources)).is_equal_to(
        (baseline.id, baseline.requires, baseline.related, baseline.resources)
    )
    assert_that([str(item.path) for item in start.payload]).is_equal_to(
        [str(item.path) for item in baseline.payload]
    )
    for payload in start.payload:
        source = root / start.source_path / payload.path
        assert_that(payload.sha256).is_equal_to(
            hashlib.sha256(source.read_bytes()).hexdigest()
        )
    assert_that([item for item in result.diagnostics if not item.warning]).is_empty()
    attribute = next(item for item in start.host_attributes if item.key == key)
    assert_that(json.loads(attribute.value_json)).is_equal_to(normalized)
    assert_that(attribute.semantics).is_equal_to(
        "unknown" if key == "vendor-permission" else "invocation-restriction"
    )
    assert_that(attribute.rule_for("claude-code")).is_equal_to(
        "refuse" if key == "vendor-permission" else "preserve"
    )
    if key == "vendor-permission":
        assert_that(dict(attribute.hosts)).is_equal_to(
            {"claude-code": "unverified", "codex": "unverified", "cursor": "unverified"}
        )
        assert_that(
            [
                item.message
                for item in result.diagnostics
                if item.code == "inventory.unknown-frontmatter"
                and item.location == str(start.id)
            ]
        ).contains("Unknown frontmatter key: vendor-permission")
    assert_that(attribute.rule_for("cursor")).is_equal_to("refuse")
    assert_that(attribute.rule_for("cursor", strict=False)).is_equal_to("unverified")
    assert_that(attribute.rule_for("unknown")).is_equal_to("refuse")
    args = [
        "inventory",
        "--repo-root",
        str(root),
        "--vendor-root",
        f"vendor={vendor}",
        "--json",
    ]
    assert_that(cli.main(args)).is_zero()
    first = capsys.readouterr().out
    assert_that(first).is_equal_to(result.to_json())
    assert_that(cli.main(args)).is_zero()
    assert_that(capsys.readouterr().out).is_equal_to(first)


@pytest.mark.parametrize("key", ["disable-model-invocation", "vendor-permission"])
@pytest.mark.parametrize(
    "yaml_value,reason",
    [
        ("!!binary aGVsbG8=", "bytes"),
        ("!!set {one: null}", "set"),
        ("{nested: .inf}", "non-finite"),
        ("&cycle [*cycle]", "recursive"),
        ("&cycle {nested: *cycle}", "recursive"),
        ("[" * 70 + "true" + "]" * 70, "depth"),
        ("[" + ",".join(["true"] * 10001) + "]", "budget"),
    ],
    ids=[
        "binary",
        "set",
        "nonfinite",
        "recursive-list",
        "recursive-map",
        "deep",
        "wide",
    ],
)
def test_unsupported_attribute_is_local_actionable_error(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    key: str,
    yaml_value: str,
    reason: str,
) -> None:
    """Invalid attribute data fails CLI while preserving valid payload and edges."""
    root, vendor = inventory_repo
    before = load_inventory(root, vendor_roots={"vendor": vendor})
    baseline = next(item for item in before.capabilities if item.id.name == "stable")
    path = root / "skills/start/SKILL.md"
    path.write_text(
        path.read_text().replace(
            "disable-model-invocation: true", f"{key}: {yaml_value}"
        )
    )
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    start = next(item for item in result.capabilities if item.id.name == "stable")
    assert_that((start.requires, start.related, start.resources)).is_equal_to(
        (baseline.requires, baseline.related, baseline.resources)
    )
    assert_that(start.payload).is_not_empty()
    findings = [item for item in result.diagnostics if not item.warning]
    assert_that(findings).is_length(1)
    assert_that(findings[0].code).is_equal_to("inventory.invalid-host-attribute")
    assert_that(findings[0].location).is_equal_to(str(start.id))
    assert_that(findings[0].message).contains(key, reason)
    assert_that([item.key for item in start.host_attributes]).does_not_contain(key)
    if key == "vendor-permission":
        assert_that([item.code for item in result.diagnostics]).contains(
            "inventory.unknown-frontmatter"
        )
    assert_that(
        cli.main(
            [
                "inventory",
                "--repo-root",
                str(root),
                "--vendor-root",
                f"vendor={vendor}",
                "--json",
            ]
        )
    ).is_equal_to(1)
    assert_that(json.loads(capsys.readouterr().out)).is_equal_to(
        json.loads(result.to_json())
    )


def test_unknown_fields_keep_values_without_inventing_host_semantics(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown fields are inert data; portable and known keys keep their contracts."""
    root, vendor = inventory_repo

    def forbidden(*args: object, **kwargs: object) -> None:
        """Reject process execution while collecting source metadata."""
        pytest.fail("Inventory must not execute metadata or vendor payloads")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    path = root / "skills/start/SKILL.md"
    original = path.read_text()
    value = "{allow: [safe-tool], command: 'touch MUST-NOT-EXECUTE'}"
    path.write_text(
        original.replace(
            "surprise: inert",
            "surprise: inert\n"
            "license: MIT\ncompatibility: Any host\nmetadata: {author: fixture}\n"
            f"vendor-permission: {value}",
        )
    )
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    start = next(item for item in result.capabilities if item.id.name == "stable")
    attributes = {item.key: item for item in start.host_attributes}
    assert_that(set(attributes)).is_equal_to(
        {"disable-model-invocation", "surprise", "vendor-permission"}
    )
    unknown = attributes["vendor-permission"]
    assert_that(json.loads(unknown.value_json)).is_equal_to(
        {"allow": ["safe-tool"], "command": "touch MUST-NOT-EXECUTE"}
    )
    assert_that(unknown.semantics).is_equal_to("unknown")
    assert_that(json.loads(attributes["surprise"].value_json)).is_equal_to("inert")
    known = attributes["disable-model-invocation"]
    assert_that(known.semantics).is_equal_to("invocation-restriction")
    assert_that(known.rule_for("claude-code")).is_equal_to("preserve")
    for host in ("claude-code", "codex", "cursor", "new-host"):
        assert_that(unknown.rule_for(host)).is_equal_to("refuse")
        assert_that(unknown.rule_for(host, strict=False)).is_equal_to("unverified")
    args = [
        "inventory",
        "--repo-root",
        str(root),
        "--vendor-root",
        f"vendor={vendor}",
        "--json",
    ]
    assert_that(cli.main(args)).is_zero()
    first = capsys.readouterr().out
    assert_that(first).is_equal_to(result.to_json())
    record = next(
        item
        for item in json.loads(first)["capabilities"]
        if item["id"] == str(start.id)
    )
    serialized = next(
        item for item in record["host_attributes"] if item["key"] == unknown.key
    )
    assert_that(serialized["value_json"]).is_equal_to(unknown.value_json)
    assert_that(cli.main(args)).is_zero()
    assert_that(capsys.readouterr().out).is_equal_to(first)
    path.write_text(
        path.read_text().replace(
            value, "{command: 'touch MUST-NOT-EXECUTE', allow: [safe-tool]}"
        )
    )
    reordered = load_inventory(root, vendor_roots={"vendor": vendor})
    reordered_start = next(
        item for item in reordered.capabilities if item.id == start.id
    )
    assert_that(reordered_start.host_attributes).is_equal_to(start.host_attributes)
    assert_that(
        (reordered_start.requires, reordered_start.related, reordered_start.resources)
    ).is_equal_to((start.requires, start.related, start.resources))
    assert_that(list(root.rglob("MUST-NOT-EXECUTE"))).is_empty()
    assert_that(list(vendor.rglob("MUST-NOT-EXECUTE"))).is_empty()
