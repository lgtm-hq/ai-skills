"""Public planning regressions for rejected inputs, advisory edges and key ownership."""

import json
from collections import Counter
from pathlib import Path

import pytest
from assertpy import assert_that
from inventory_helpers import snapshot
from selection_helpers import PREFIX, inventory_graph, plan

from ai_skills_engine import cli
from ai_skills_engine.inventory.load import load_inventory
from ai_skills_engine.inventory.model import Inventory
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.migrations import migrate
from ai_skills_engine.selection import rules

pytest_plugins = ["inventory_helpers"]


def run_plan(
    *, root: Path, vendor: Path, capsys: pytest.CaptureFixture[str], expected: int
) -> dict:
    """Exercise the public CLI and verify the complete input snapshot.

    Args:
        root: Consumer manifest root.
        vendor: Offline vendor snapshot.
        capsys: CLI output capture.
        expected: Expected process status.

    Returns:
        Parsed public JSON result.
    """
    before = snapshot(root, vendor)
    assert_that(
        cli.main(
            [
                "plan",
                "--json",
                "--repo-root",
                str(root),
                "--vendor-root",
                f"vendor={vendor}",
            ]
        )
    ).is_equal_to(expected)
    output = json.loads(capsys.readouterr().out)
    assert_that(snapshot(root, vendor)).is_equal_to(before)
    return output


@pytest.mark.parametrize(
    ("control", "expected"),
    [("exclude", 0), ("narrow", 0), ("kept", 1), ("required", 1), ("stale", 1)],
)
@pytest.mark.parametrize("source", ["mapped", "manifest", "local"])
def test_rejected_payload_selection(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    control: str,
    expected: int,
    source: str,
) -> None:
    """Declared/discovered failures can be trimmed, but never retained or invented."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    owner = root if source == "local" else vendor
    broken = owner / "skills/broken"
    broken.mkdir()
    (broken / "SKILL.md").write_text("---\nname: broken\n---\nbody\n")
    publisher = "fixture" if source == "local" else "vendor"
    identity = f"{publisher}/tools:skill/broken"
    boundary = document["packages"][0] if source == "local" else document["vendors"][0]
    if source == "local":
        boundary["capabilities"].append({"id": "broken", "path": "skills/broken"})
    elif source == "manifest":
        document["vendors"][0].pop("mapping")
        (vendor / "ai-skills.yaml").write_text(
            dump_document(
                {
                    "apiVersion": "ai-skills.dev/v1",
                    "publisher": {"id": "vendor"},
                    "packages": [
                        {
                            "id": "tools",
                            "capabilities": [
                                {"id": "helper", "path": "skills/help"},
                                {"id": "broken", "path": "skills/broken"},
                            ],
                        }
                    ],
                }
            )
        )
        (vendor / "skills/help/SKILL.md").write_text(
            "---\nname: help\ndescription: Helper.\n---\n"
        )
    if control in {"exclude", "stale"}:
        boundary["exclude"] = [
            identity if control == "exclude" else f"{publisher}/tools:skill/absent"
        ]
    elif control == "narrow":
        boundary["include"] = [
            (
                "fixture/tools:skill/stable"
                if source == "local"
                else "vendor/tools:skill/helper"
            )
        ]
    elif control == "required":
        boundary["include"] = []
        document["packages"][0]["include"] = ["fixture/tools:skill/stable"]
        document["packages"][0]["capabilities"][0]["requires"] = [identity]
    (root / "ai-skills.yaml").write_text(dump_document(document))
    if control == "exclude":
        inventory = load_inventory(
            root, vendor_roots={"vendor": vendor}, selection_candidates=True
        )
        assert_that(tuple(map(str, inventory.rejected))).contains(identity)
        assert_that(
            tuple(str(item.id) for item in inventory.capabilities)
        ).does_not_contain(identity)
        assert_that([item.code for item in inventory.diagnostics]).contains(
            "inventory.invalid-payload"
        )
    output = run_plan(root=root, vendor=vendor, capsys=capsys, expected=expected)
    codes = [item["code"] for item in output["diagnostics"]]
    if control == "stale":
        assert_that(codes).contains("selection.selector-unmatched")
    else:
        assert_that(codes).does_not_contain("selection.selector-unmatched")
    if expected == 0:
        assert_that(codes).does_not_contain("inventory.invalid-payload")
        entry = next(item for item in output["capabilities"] if item["id"] == identity)
        assert_that(entry["state"]).is_equal_to("excluded")
    else:
        assert_that(codes).contains("inventory.invalid-payload")


@pytest.mark.parametrize(
    "control", ["unused", "exclude", "required", "required-excluded"]
)
def test_rejected_resource_selection(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    control: str,
) -> None:
    """Uncollected resource data is optional only outside the retained closure."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    package = document["packages"][0]
    identity = "fixture/tools:resource/missing"
    package["resources"].append({"id": "missing", "path": "absent.txt"})
    if "required" in control:
        package["capabilities"][0]["resources"].append(identity)
    if "exclude" in control:
        package["exclude"] = [identity]
    (root / "ai-skills.yaml").write_text(dump_document(document))
    output = run_plan(
        root=root,
        vendor=vendor,
        capsys=capsys,
        expected=1 if "required" in control else 0,
    )
    codes = [item["code"] for item in output["diagnostics"]]
    assert_that(codes).does_not_contain("selection.selector-unmatched")
    if "required" in control:
        assert_that(codes).contains(
            "selection.required-excluded"
            if "exclude" in control
            else "inventory.invalid-resource"
        )


@pytest.mark.parametrize("control", ["excluded", "narrow", "kept"])
def test_payload_resource_grants_follow_retained_capabilities(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    control: str,
) -> None:
    """Excluded bad resource links do not veto unrelated roots; kept links fail."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    (vendor / "skills/broken").mkdir()
    (vendor / "skills/broken/SKILL.md").write_text(
        "---\nname: broken\ndescription: Broken links.\n---\n"
        "[missing](../../absent.txt)\n"
    )
    if control == "excluded":
        document["vendors"][0]["exclude"] = ["vendor/tools:skill/broken"]
    elif control == "narrow":
        document["vendors"][0]["include"] = ["vendor/tools:skill/helper"]
    (root / "ai-skills.yaml").write_text(dump_document(document))
    output = run_plan(
        root=root, vendor=vendor, capsys=capsys, expected=1 if control == "kept" else 0
    )
    assert_that(
        "inventory.undeclared-resource"
        in [item["code"] for item in output["diagnostics"]]
    ).is_equal_to(control == "kept")


@pytest.mark.parametrize(
    "code",
    [
        "inventory.invalid-payload",
        "inventory.invalid-resource",
        "inventory.duplicate-id",
        "inventory.unknown-requires",
    ],
)
def test_diagnostic_locations_are_not_candidate_identity_evidence(code: str) -> None:
    """Arbitrary diagnostic locations cannot authorize suppressing collection errors."""
    result = rules.select(
        Inventory(
            capabilities=(),
            resources=(),
            diagnostics=(
                Diagnostic(code, "vendor/tools:skill/fake", "untrusted location"),
            ),
        )
    )
    assert_that(result.valid).is_false()
    assert_that([item.code for item in result.diagnostics]).contains(code)


@pytest.mark.parametrize("field", ["related", "requires"])
def test_missing_edge_preserves_direction_and_inventory_semantics(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    field: str,
) -> None:
    """Only selection makes missing related edges advisory, with their witness."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    target = "fixture/tools:skill/absent"
    document["packages"][0]["capabilities"][0][field] = [target]
    (root / "ai-skills.yaml").write_text(dump_document(document))
    inventory = load_inventory(root, vendor_roots={"vendor": vendor})
    finding = next(
        item
        for item in inventory.diagnostics
        if item.code == f"inventory.unknown-{field}"
    )
    assert_that(finding.warning).is_false()
    output = run_plan(
        root=root, vendor=vendor, capsys=capsys, expected=0 if field == "related" else 1
    )
    if field == "related":
        assert_that(output["dangling_related"]).contains(
            ["fixture/tools:skill/stable", target]
        )
        finding = next(
            item
            for item in output["diagnostics"]
            if item["code"] == "selection.dangling-related"
            and item["chain"][-1] == target
        )
        assert_that(finding["chain"]).is_equal_to(
            ["fixture/tools:skill/stable", target]
        )
        assert_that(finding["warning"]).is_true()


@pytest.mark.parametrize("excluded", [False, True])
def test_wildcard_requirement_cannot_hide_a_rejected_member(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    excluded: bool,
) -> None:
    """A wildcard matching valid and rejected payloads must retain both witnesses."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    (vendor / "skills/broken").mkdir()
    (vendor / "skills/broken/SKILL.md").write_text("---\nname: broken\n---\nbody\n")
    identity = "vendor/tools:skill/broken"
    document["packages"][0]["capabilities"][0]["requires"] = ["vendor/tools:skill/*"]
    document["vendors"][0]["include"] = []
    if excluded:
        document["vendors"][0]["exclude"] = [identity]
    (root / "ai-skills.yaml").write_text(dump_document(document))
    output = run_plan(root=root, vendor=vendor, capsys=capsys, expected=1)
    finding = next(
        item
        for item in output["diagnostics"]
        if item["code"]
        == ("selection.required-excluded" if excluded else "selection.required-missing")
    )
    assert_that(finding["chain"]).is_equal_to(["fixture/tools:skill/stable", identity])


@pytest.mark.parametrize("role", ["integration", "lifecycle"])
@pytest.mark.parametrize(
    "control", ["collision", "multi-rename", "single-rename", "skip"]
)
def test_configuration_key_collision_controls(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    role: str,
    control: str,
) -> None:
    """Capability-wide multi-key renames fail without erasing the other key."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    package = document["packages"][0]
    original = next(
        item for item in package["capabilities"] if item.get("role") == role
    )
    field = "mcpServers" if role == "integration" else "hooks"
    value = (
        {"command": "true"}
        if role == "integration"
        else [{"hooks": [{"type": "command", "command": "true"}]}]
    )
    keys = ["alpha", "beta"] if control != "single-rename" else ["beta"]
    (root / original["path"]).write_text(
        json.dumps({field: dict.fromkeys(keys, value)})
    )
    other = root / "other.json"
    other.write_text(json.dumps({field: {"beta": value}}))
    package["capabilities"].append({"id": "second", "path": "other.json", "role": role})
    if control != "collision":
        document["overrides"] = {
            "collisions": [
                {
                    "capability": f"fixture/tools:{role}/{original['id']}",
                    "action": "skip" if control == "skip" else "rename",
                    **({} if control == "skip" else {"name": "renamed"}),
                }
            ]
        }
    (root / "ai-skills.yaml").write_text(dump_document(document))
    output = run_plan(
        root=root,
        vendor=vendor,
        capsys=capsys,
        expected=1 if control in {"collision", "multi-rename"} else 0,
    )
    if control == "multi-rename":
        assert_that([item["code"] for item in output["diagnostics"]]).contains(
            "selection.invalid-collision-override", "selection.namespace-collision"
        )
        beta = next(item for item in output["namespace"] if item[:2] == [role, "beta"])
        assert_that(beta[2]).is_length(2)


def test_terminating_migration_reuses_package_rule_in_real_plan(
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A capability rename can revisit a package rule without cycling."""
    assert_that(
        migrate(
            "a/pkg:skill/old", {"a/pkg": "b/pkg", "b/pkg:skill/old": "a/pkg:skill/new"}
        )
    ).is_equal_to("b/pkg:skill/new")
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    document["packages"][0]["include"] = ["old/tools:skill/old"]
    document["overrides"] = {
        "migrations": [
            {"from": "old/tools", "to": "fixture/tools"},
            {"from": "fixture/tools:skill/old", "to": "old/tools:skill/stable"},
        ]
    }
    (root / "ai-skills.yaml").write_text(dump_document(document))
    run_plan(root=root, vendor=vendor, capsys=capsys, expected=0)


@pytest.mark.parametrize(
    "migrations",
    [
        {"a/pkg": "b/pkg", "b/pkg": "a/pkg"},
        {"a/pkg": "a/pkg:skill/new"},
    ],
)
def test_real_and_expanding_migration_cycles_fail(migrations: dict[str, str]) -> None:
    """Exact cycles and growing prefix rewrites terminate with an error."""
    with pytest.raises(ValueError, match="Cyclic"):
        migrate("a/pkg:skill/old", migrations)


def test_successful_paths_are_built_only_for_final_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Instrument full planner calls, preserving every final witness and SCC bound."""
    counts: Counter[str] = Counter()
    original = rules.dependency_chain

    def counted(*, parents: dict[str, str | None], target: str) -> tuple[str, ...]:
        """Record full path requests without changing their behavior."""
        counts[target] += 1
        return original(parents=parents, target=target)

    monkeypatch.setattr(rules, "dependency_chain", counted)
    names = [f"node-{index}" for index in range(50)]
    graph = inventory_graph(
        {
            "capabilities": {
                name: {"requires": names[index + 1 : index + 2]}
                for index, name in enumerate(names)
            }
        }
    )
    result = plan(graph, include=(PREFIX + names[0],))
    assert_that(result.valid).is_true()
    assert_that(set(counts.values())).is_equal_to({1})
    assert_that(
        next(
            item for item in result.capabilities if item.id == PREFIX + names[-1]
        ).chain
    ).is_equal_to(tuple(PREFIX + name for name in names))
