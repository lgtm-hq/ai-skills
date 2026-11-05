"""Error/warning regressions at actual inventory and manifest CLI boundaries."""

import json
from pathlib import Path
from typing import cast

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.inventory import host_attributes, load_inventory
from ai_skills_engine.inventory.host_attribute import HostAttribute
from ai_skills_engine.inventory.host_attributes import load_host_attributes
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document

pytest_plugins = ["inventory_helpers"]


@pytest.mark.parametrize(
    "field,target,code",
    [
        ("requires", "fixture/tools:skill/absent", "inventory.unknown-requires"),
        ("related", "fixture/tools:workflow/absent", "inventory.unknown-related"),
        ("requires", "fixture/tools:skill/stable", "inventory.self-requires"),
        ("requires", "outsider/tools:skill/help", "inventory.non-imported-requires"),
        ("resources", "fixture/tools:resource/absent", "inventory.unknown-resources"),
    ],
)
def test_declared_target_errors_reach_manifest_cli(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    field: str,
    target: str,
    code: str,
) -> None:
    """Each invalid declared edge fails both production commands with its code."""
    root, vendor = inventory_repo
    path = root / "ai-skills.yaml"
    document = read_document(path)
    document["packages"][0]["capabilities"][0][field] = [target]
    path.write_text(dump_document(document))
    for command in (["inventory", "--json"], ["manifest", "validate"]):
        assert_that(
            cli.main(
                [
                    *command,
                    "--repo-root",
                    str(root),
                    "--vendor-root",
                    f"vendor={vendor}",
                ]
            )
        ).is_equal_to(1)
        assert_that(capsys.readouterr().out).contains(code)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("[outside](../../outside.md)", True),
        ("![image](../../outside.md)", True),
        ("[unused]: ../../outside.md", True),
        ("> [unused]: ../../outside.md", True),
        ("[encoded](../../%6futside.md?x=1#fragment)", True),
        ("[prefix](../../shared-evil/file.md)", True),
        ("[absolute](/etc/passwd)", True),
        ("[scheme](file:///etc/passwd)", True),
        ("[script](javascript:alert(1))", True),
        ("[backslash](..%5coutside.md)", True),
        ("[nul](bad%00path)", True),
        ("[inside](SKILL.md#start)", False),
        ("[shared](../../shared/guide.md?raw=1#start)", False),
        ("[remote](https://example.test/outside.md)", False),
        ("[anchor](#start)", False),
        ("`[literal](../../outside.md)`", False),
        ("```md\n[example](../../outside.md)\n```", False),
        ("    [example](../../outside.md)", False),
        ("A literal path ../../outside.md is prose.", False),
        ("<div>../../outside.md</div>", False),
    ],
)
def test_markdown_link_boundary_controls(
    inventory_repo: tuple[Path, Path], text: str, expected: bool
) -> None:
    """Only structural Markdown destinations cross the declared resource boundary."""
    root, vendor = inventory_repo
    path = root / "skills/start/SKILL.md"
    path.write_text("---\nname: start\ndescription: Entry.\n---\n" + text + "\n")
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    findings = [
        item
        for item in result.diagnostics
        if item.code == "inventory.undeclared-resource"
    ]
    assert_that(bool(findings)).is_equal_to(expected)
    start = next(item for item in result.capabilities if item.id.name == "stable")
    assert_that([str(item) for item in start.requires]).is_equal_to(
        ["vendor/tools:skill/helper"]
    )


def test_mention_and_link_lint_never_create_edges(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Name matches warn; a real sibling-capability link errors; neither adds edges."""
    root, vendor = inventory_repo
    path = root / "skills/start/SKILL.md"
    path.write_text(path.read_text() + "\n[reviewer](../../agents/specialist.md)\n")
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.undeclared-mention",
        "inventory.undeclared-resource",
        "inventory.unknown-frontmatter",
    )
    start = next(item for item in result.capabilities if item.id.name == "stable")
    assert_that([str(item) for item in start.related]).is_equal_to(
        ["fixture/tools:workflow/procedure"]
    )
    assert_that([str(item) for item in start.requires]).is_equal_to(
        ["vendor/tools:skill/helper"]
    )
    path.write_text(
        "---\nname: start\ndescription: Entry.\n---\n`reviewer`\n\n```\nreviewer\n```\n"
    )
    inert = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that(
        [
            item
            for item in inert.diagnostics
            if item.code == "inventory.undeclared-mention"
            and item.location == str(start.id)
        ]
    ).is_empty()


@pytest.mark.parametrize(
    "operand", ["../outside", "/etc/passwd", "skills/start/link", "alias/start"]
)
def test_payload_path_and_symlink_boundary(
    inventory_repo: tuple[Path, Path], operand: str
) -> None:
    """Ancestors and leaf symlinks cannot bypass the safe payload boundary."""
    root, vendor = inventory_repo
    (root / "skills/start/link").symlink_to(root / "skills/start/SKILL.md")
    (root / "alias").symlink_to(root / "skills", target_is_directory=True)
    document = read_document(root / "ai-skills.yaml")
    document["packages"][0]["capabilities"][0]["path"] = operand
    (root / "ai-skills.yaml").write_text(dump_document(document))
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.invalid-payload"
    )


def test_resource_declarations_do_not_allow_arbitrary_external_links(
    inventory_repo: tuple[Path, Path],
) -> None:
    """A package resource must be referenced by the capability, not just exist."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    document["packages"][0]["capabilities"][0]["resources"] = []
    (root / "ai-skills.yaml").write_text(dump_document(document))
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.undeclared-resource"
    )
    document["packages"][0]["resources"][0]["path"] = "missing"
    (root / "ai-skills.yaml").write_text(dump_document(document))
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.invalid-resource"
    )


@pytest.mark.parametrize(
    "semantics", ["invocation-restriction", "activation", "permission"]
)
@pytest.mark.parametrize("rule", ["drop", "invented", "map:", "map:   "])
def test_host_table_rejects_loss_and_invalid_rules(semantics: str, rule: str) -> None:
    """Invalid packaged rules fail closed, especially behavior-widening drops."""
    text = dump_document(
        {
            "restriction": {
                "semantics": semantics,
                "hosts": {
                    "claude-code": "preserve",
                    "codex": rule,
                    "cursor": "unverified",
                },
            }
        }
    )
    with pytest.raises(ValueError, match="invalid rule"):
        load_host_attributes(text)


@pytest.mark.parametrize(
    "text",
    [
        "[]",
        "a: {}",
        "a: {semantics: permission, hosts: {codex: refuse}}",
        "a: {semantics: 3, hosts: {}}",
        "a: {semantics: permission, hosts: []}",
    ],
)
def test_host_table_requires_explicit_per_host_rules(text: str) -> None:
    """Missing or untyped host semantics cannot become implicit preservation."""
    with pytest.raises((TypeError, ValueError)):
        load_host_attributes(text)


def test_host_rules_are_conservative_and_values_retained(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Uncertainty and unknown hosts refuse strict projection without mutating data."""
    root, vendor = inventory_repo
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    start = next(item for item in result.capabilities if item.id.name == "stable")
    restriction = start.host_attributes[0]
    assert_that(json.loads(restriction.value_json)).is_true()
    assert_that(restriction.semantics).is_equal_to("invocation-restriction")
    assert_that(restriction.rule_for("claude-code")).is_equal_to("preserve")
    for host in ("codex", "cursor", "unknown-interface"):
        assert_that(restriction.rule_for(host)).is_equal_to("refuse")
        assert_that(restriction.rule_for(host, strict=False)).is_equal_to("unverified")
    mapped = HostAttribute(
        key="a",
        value_json="false",
        semantics="permission",
        hosts=(("codex", "map:allowed_tools"), ("cursor", "refuse")),
    )
    assert_that(mapped.rule_for("codex")).is_equal_to("map:allowed_tools")
    assert_that(mapped.rule_for("cursor", strict=False)).is_equal_to("refuse")


def test_resource_markdown_and_invalid_utf8_are_checked(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Resource documents retain the same boundary and malformed bytes fail visibly."""
    root, vendor = inventory_repo
    (root / "shared/guide.md").write_text("[external input](../undeclared.txt)\n")
    (root / "skills/start/broken.md").write_bytes(b"\xff")
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.undeclared-resource", "inventory.invalid-payload"
    )


def test_direct_host_record_rejects_drop() -> None:
    """Frozen host records cannot bypass table validation by direct construction."""
    with pytest.raises(ValueError, match="drop is forbidden"):
        HostAttribute(
            key="disable-model-invocation",
            value_json="true",
            semantics="invocation-restriction",
            hosts=(("codex", "drop"),),
        )


def test_frontmatter_edges_are_inert(inventory_repo: tuple[Path, Path]) -> None:
    """Frontmatter edge-like keys warn without granting dependencies or resources."""
    root, vendor = inventory_repo
    path = root / "skills/start/SKILL.md"
    path.write_text(
        "---\nname: start\ndescription: Entry.\n"
        "requires: [outsider/tools:skill/start]\n"
        "related: [vendor/tools:specialist/reviewer]\n"
        "resources: [fixture/tools:resource/undeclared]\n---\n"
    )
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    start = next(item for item in result.capabilities if item.id.name == "stable")
    assert_that([str(item) for item in start.requires]).is_equal_to(
        ["vendor/tools:skill/helper"]
    )
    assert_that([str(item) for item in start.related]).is_equal_to(
        ["fixture/tools:workflow/procedure"]
    )
    assert_that([str(item) for item in start.resources]).is_equal_to(
        ["fixture/tools:resource/guide"]
    )
    assert_that(
        [
            item
            for item in result.diagnostics
            if item.code == "inventory.unknown-frontmatter"
            and item.location == str(start.id)
        ]
    ).is_length(3)


def test_packaged_host_rules_load_once_per_process(
    inventory_repo: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every capability reuses one validated packaged host-rule table."""
    root, vendor = inventory_repo
    calls: list[str | None] = []

    def counting(text: str | None = None) -> dict[str, dict[str, object]]:
        """Count packaged-table validations, then run the real loader."""
        calls.append(text)
        return load_host_attributes(text)

    host_attributes._packaged_host_attributes.cache_clear()
    monkeypatch.setattr(host_attributes, "load_host_attributes", counting)
    try:
        result = load_inventory(root, vendor_roots={"vendor": vendor})
    finally:
        host_attributes._packaged_host_attributes.cache_clear()
    assert_that(len(result.capabilities)).is_greater_than(1)
    assert_that(calls).is_equal_to([None])


@pytest.mark.parametrize(
    "rule",
    ["preserve", "refuse", "unverified", "map:x", "map: x", "map:", "drop", 1],
)
def test_loader_and_record_share_one_rule_grammar(rule: object) -> None:
    """The packaged-table loader and direct records accept exactly the same rules."""
    hosts = {"claude-code": rule, "codex": "preserve", "cursor": "preserve"}
    text = json.dumps({"key": {"semantics": "permission", "hosts": hosts}})
    try:
        load_host_attributes(text)
        loaded = True
    except ValueError:
        loaded = False
    try:
        HostAttribute(
            key="key",
            value_json="1",
            semantics="permission",
            hosts=cast(tuple[tuple[str, str], ...], (("claude-code", rule),)),
        )
        constructed = True
    except (TypeError, ValueError):
        constructed = False
    assert_that(loaded).is_equal_to(constructed)
    assert_that(loaded).is_equal_to(
        rule in {"preserve", "refuse", "unverified", "map:x"}
    )


def test_schema_errors_print_formatted_diagnostics(
    inventory_repo: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Structural schema errors read like other diagnostics, not Python reprs."""
    root, vendor = inventory_repo
    path = root / "ai-skills.yaml"
    document = read_document(path)
    document["packages"][0]["bogus"] = 1
    path.write_text(dump_document(document))
    with pytest.raises(ValueError, match=r"^schema /packages/0: ") as raised:
        load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that(str(raised.value)).does_not_contain("Diagnostic(")
    capsys.readouterr()
    status = cli.main(
        ["--repo-root", str(root), "inventory", "--vendor-root", f"vendor={vendor}"]
    )
    assert_that(status).is_equal_to(1)
    error = capsys.readouterr().err
    assert_that(error).contains("schema /packages/0:").does_not_contain("Diagnostic(")


def test_consumer_schema_errors_print_formatted_diagnostics(
    inventory_repo: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """load_consumer's structural errors read like other diagnostics too."""
    root, vendor = inventory_repo
    path = root / "ai-skills.yaml"
    document = read_document(path)
    document["publisher"]["id"] = 7
    path.write_text(dump_document(document))
    capsys.readouterr()
    for command in (["inventory"], ["manifest", "validate"]):
        status = cli.main(
            ["--repo-root", str(root), *command, "--vendor-root", f"vendor={vendor}"]
        )
        assert_that(status).is_equal_to(1)
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert_that(output).contains("schema /publisher/id:").does_not_contain(
            "Diagnostic("
        )
