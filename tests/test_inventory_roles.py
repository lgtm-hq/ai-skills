"""Role and dialect shapes distinguish declarative execution from inert examples."""

from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.inventory import load_inventory
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document

pytest_plugins = ["inventory_helpers"]


@pytest.mark.parametrize(
    "role,path",
    [
        ("skill", "agents/specialist.md"),
        ("specialist", "skills/start"),
        ("workflow", "rules/rule.mdc"),
        ("lifecycle", "commands/procedure.md"),
        ("integration", "hooks/hooks.json"),
        ("instruction", "mcp/servers.json"),
    ],
)
def test_role_mismatch_fails_at_entrypoint(
    inventory_repo: tuple[Path, Path],
    role: str,
    path: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A declared role cannot relabel a differently shaped payload."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    document["packages"][0]["capabilities"] = [
        {"id": "bad", "role": role, "path": path}
    ]
    (root / "ai-skills.yaml").write_text(dump_document(document))
    assert_that(
        cli.main(
            [
                "inventory",
                "--json",
                "--repo-root",
                str(root),
                "--vendor-root",
                f"vendor={vendor}",
            ]
        )
    ).is_equal_to(1)
    assert_that(capsys.readouterr().out).contains("inventory.invalid-payload")


@pytest.mark.parametrize(
    "path,text",
    [
        (
            "hooks/hooks.json",
            '{"documentation": "hooks SessionStart command touch file"}',
        ),
        (
            "hooks/hooks.json",
            (
                '{"hooks": {"SessionStart": [{"hooks": '
                '[{"type": "command", "command": ""}]}]}}'
            ),
        ),
        ("hooks/hooks.json", '{"hooks": {"SessionStart": []}}'),
        ("hooks/hooks.json", '{"hooks": {}, "hooks": {}}'),
        ("mcp/servers.json", '{"documentation": "command or url"}'),
        ("mcp/servers.json", '{"mcpServers": {"fake": {"command": 42}}}'),
        ("mcp/servers.json", '{"mcpServers": {}}'),
        ("mcp/servers.json", "[]"),
        (
            "skills/start/SKILL.md",
            "---\nname: start\nname: duplicate\ndescription: Good.\n---\n",
        ),
        ("skills/start/SKILL.md", "---\nname: start\ndescription: []\n---\n"),
        (
            "agents/specialist.md",
            "A literal specialist example without required frontmatter.",
        ),
    ],
)
def test_inert_configuration_mentions_do_not_satisfy_shapes(
    inventory_repo: tuple[Path, Path], path: str, text: str
) -> None:
    """Payload shape checks inspect actual declarations rather than keyword text."""
    root, vendor = inventory_repo
    (root / path).write_text(text)
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.invalid-payload"
    )


def test_plain_instruction_and_no_role_inference(
    inventory_repo: tuple[Path, Path],
) -> None:
    """Explicit plain Markdown instructions load; omitting role defaults to skill."""
    root, vendor = inventory_repo
    (root / "instructions.md").write_text("Always preserve the requested scope.\n")
    document = read_document(root / "ai-skills.yaml")
    document["packages"][0]["capabilities"].append(
        {"id": "plain", "role": "instruction", "path": "instructions.md"}
    )
    (root / "ai-skills.yaml").write_text(dump_document(document))
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    instruction = next(item for item in result.capabilities if item.id.name == "plain")
    assert_that(str(instruction.dialect)).is_equal_to("markdown-instruction")
    document["packages"][0]["capabilities"][-1].pop("role")
    (root / "ai-skills.yaml").write_text(dump_document(document))
    result = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([item.code for item in result.diagnostics]).contains(
        "inventory.invalid-payload"
    )
