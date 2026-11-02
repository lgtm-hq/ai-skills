"""Host YAML values retain capability identity, payload and declared edges."""

import hashlib
import json
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.inventory import load_inventory

pytest_plugins = ["inventory_helpers"]


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
            "disable-model-invocation: true", "disable-model-invocation: " + yaml_value
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
    attribute = start.host_attributes[0]
    assert_that(json.loads(attribute.value_json)).is_equal_to(normalized)
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
            "disable-model-invocation: true", "disable-model-invocation: " + yaml_value
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
    assert_that(findings[0].message).contains("disable-model-invocation", reason)
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
