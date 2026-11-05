"""Named core rules and the five hard cases over fixture inventories."""

from dataclasses import replace
from pathlib import PurePosixPath

import pytest
from assertpy import assert_that
from selection_helpers import (
    PREFIX,
    RESOURCE,
    change,
    errors,
    inventory_graph,
    plan,
    selected,
)

from ai_skills_engine.inventory.model import CapabilityId, Inventory
from ai_skills_engine.manifest.deny import Deny
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.manifest.identity import matches
from ai_skills_engine.manifest.migration import Migration
from ai_skills_engine.manifest.overrides import Overrides
from ai_skills_engine.manifest.policy import Policy
from ai_skills_engine.provenance.origins import denied_origin
from ai_skills_engine.selection import select
from ai_skills_engine.selection.deny import deny_matches
from ai_skills_engine.selection.deny_subject import DenySubject
from ai_skills_engine.selection.explain import explain

pytest_plugins = ["selection_helpers"]


def test_rule_one_absent_include_vs_empty(selection_inventory: Inventory) -> None:
    """Absent include roots all capabilities; empty include roots none."""
    all_result = plan(selection_inventory)
    assert_that(selected(all_result)).is_equal_to(
        {str(item.id) for item in selection_inventory.capabilities}
    )
    empty = plan(selection_inventory, include=())
    assert_that(selected(empty)).is_empty()
    assert_that([item.state for item in empty.resources]).is_equal_to(["excluded"])


def test_rule_two_transitive_capability_and_resource_closure(
    selection_inventory: Inventory,
) -> None:
    """Includes bring transitive requirements and owned resources but no related."""
    result = plan(selection_inventory, include=(PREFIX + "alpha",))
    assert_that(selected(result)).is_equal_to(
        {PREFIX + name for name in ("alpha", "middle", "short", "target")}
    )
    assert_that(result.resources[0].state).is_equal_to("pulled-in")
    assert_that(result.resources[0].chain).is_equal_to((PREFIX + "alpha", RESOURCE))
    assert_that(errors(result)).is_empty()


@pytest.mark.parametrize("target", ["short", "target"])
def test_rule_three_excludes_win_without_silently_dropping_root(
    selection_inventory: Inventory, target: str
) -> None:
    """A blocked requirement remains excluded and makes its retained root invalid."""
    result = plan(
        selection_inventory, include=(PREFIX + "alpha",), exclude=(PREFIX + target,)
    )
    assert_that(selected(result)).contains(PREFIX + "alpha").does_not_contain(
        PREFIX + target
    )
    finding = next(
        item for item in errors(result) if item.code == "selection.required-excluded"
    )
    assert_that(finding.chain).starts_with(PREFIX + "alpha").ends_with(PREFIX + target)
    assert_that(finding.fix).contains(PREFIX + "alpha", PREFIX + target)
    assert_that(result.valid).is_false()


@pytest.mark.parametrize(
    "selector", [PREFIX + "absent", PREFIX + "missing*", PREFIX + "alias-alpha"]
)
def test_rule_four_unmatched_exact_wildcard_and_alias_fail(
    selection_inventory: Inventory, selector: str
) -> None:
    """Only qualified IDs match; misses never fall back to destination aliases."""
    graph = change(selection_inventory, "alpha", aliases=("alias-alpha",))
    result = plan(graph, include=(selector,))
    assert_that([item.code for item in errors(result)]).contains(
        "selection.selector-unmatched"
    )
    assert_that(errors(result)[0].fix).contains("migration")


@pytest.mark.parametrize(
    "selector", ["fixture/*", "fixture/tools", "fixture/tool*", PREFIX + "*"]
)
def test_rule_four_qualified_publisher_package_capability_selectors(
    selection_inventory: Inventory, selector: str
) -> None:
    """Supported selector forms resolve on the complete pinned identity namespace."""
    assert_that(selected(plan(selection_inventory, include=(selector,)))).is_length(
        len(selection_inventory.capabilities)
    )


def test_rule_five_requires_cycle_is_one_unit_and_partial_exclude_fails(
    selection_inventory: Inventory,
) -> None:
    """Selecting one SCC member retains all; vetoing one lists the complete SCC."""
    cycle = {PREFIX + "cycle-" + suffix for suffix in "abc"}
    kept = plan(selection_inventory, include=(PREFIX + "cycle-a",))
    assert_that(selected(kept)).is_equal_to(cycle)
    result = plan(
        selection_inventory,
        include=(PREFIX + "cycle-a",),
        exclude=(PREFIX + "cycle-b",),
    )
    finding = next(
        item for item in errors(result) if item.code == "selection.required-excluded"
    )
    assert_that(set(finding.cycle)).is_equal_to(cycle)
    assert_that(explain(result)).contains("cycle:", *cycle)


def test_rule_six_mentions_never_expand(selection_inventory: Inventory) -> None:
    """Undeclared prose evidence cannot turn into a dependency edge."""
    result = plan(selection_inventory, include=(PREFIX + "mention-a",))
    assert_that(selected(result)).is_equal_to({PREFIX + "mention-a"})
    assert_that(result.dangling_related).is_equal_to(
        ((PREFIX + "mention-a", PREFIX + "mention-b"),)
    )


@pytest.mark.parametrize("roots", [("alpha",), ("beta",), ("alpha", "beta"), ()])
def test_hard_case_shared_script_kept_by_either_and_dropped_by_neither(
    selection_inventory: Inventory, roots: tuple[str, ...]
) -> None:
    """Build-time resource retention is exactly the union of retained references."""
    result = plan(selection_inventory, include=tuple(PREFIX + name for name in roots))
    assert_that(result.resources[0].state).is_equal_to(
        "pulled-in" if roots else "excluded"
    )
    assert_that(errors(result)).is_empty()


def test_hard_case_excluded_shared_script_is_error(
    selection_inventory: Inventory,
) -> None:
    """A required resource veto cannot produce a truncated capability."""
    result = plan(selection_inventory, include=(PREFIX + "beta",), exclude=(RESOURCE,))
    assert_that(errors(result)[0].chain).is_equal_to((PREFIX + "beta", RESOURCE))
    assert_that(result.resources[0].state).is_equal_to("excluded")


@pytest.mark.parametrize("kept,removed", [("alpha", "beta"), ("beta", "alpha")])
def test_hard_case_mutual_related_removal_warns_once_per_direction(
    selection_inventory: Inventory, kept: str, removed: str
) -> None:
    """Removing either mutual reference keeps its peer and records that direction."""
    result = plan(selection_inventory, include=(PREFIX + kept,))
    assert_that(selected(result)).contains(PREFIX + kept).does_not_contain(
        PREFIX + removed
    )
    assert_that(result.dangling_related).is_equal_to(
        ((PREFIX + kept, PREFIX + removed),)
    )
    assert_that(
        [item.code for item in result.diagnostics].count("selection.dangling-related")
    ).is_equal_to(1)


def test_hard_case_origin_deny_precedes_rename_and_equal_hashes(
    selection_inventory: Inventory,
) -> None:
    """Immediate source deny survives an alias without contaminating identical bytes."""
    graph = change(
        selection_inventory,
        "target",
        origin="github.com/upstream/x",
        aliases=("renamed",),
    )
    result = plan(
        graph,
        include=(PREFIX + "alpha",),
        policy=Policy(deny=Deny(origins=("github.com/upstream/x",))),
    )
    assert_that(selected(result)).contains(PREFIX + "alpha").does_not_contain(
        PREFIX + "target"
    )
    assert_that([item.code for item in errors(result)]).contains(
        "selection.required-denied"
    )
    assert_that(
        next(item for item in result.capabilities if item.id == PREFIX + "target").state
    ).is_equal_to("denied")


def test_hard_case_required_resource_origin_deny_invalidates_requirer(
    selection_inventory: Inventory,
) -> None:
    """Deny checks bound resource origin as well as the capability's own origin."""
    result = plan(
        selection_inventory,
        include=(PREFIX + "beta",),
        policy=Policy(deny=Deny(origins=("github.com/upstream/scripts",))),
    )
    assert_that(result.valid).is_false()
    assert_that(errors(result)[0].chain).is_equal_to((PREFIX + "beta", RESOURCE))
    assert_that(
        next(item for item in result.capabilities if item.id == PREFIX + "beta").state
    ).is_equal_to("denied")
    assert_that(result.resources[0].state).is_equal_to("denied")


def test_single_deny_hook_is_lineage_ready() -> None:
    """The same hook handles future ancestor evidence on capabilities/resources."""
    policy = Policy(deny=Deny(origins=("github.com/blocked/*",)))
    resource = DenySubject(id=RESOURCE, origin="new", lineage=("github.com/blocked/x",))
    subject = DenySubject(id=PREFIX + "alpha", origin="new", resources=(resource,))
    match = deny_matches(subject, policy)
    assert_that(match).is_not_none()
    assert_that(match.chain).is_equal_to((subject.id, RESOURCE))
    assert_that(deny_matches(replace(subject, resources=()), policy)).is_none()
    assert_that(
        deny_matches(
            replace(subject, resources=(), lineage=resource.lineage), policy
        ).chain
    ).is_equal_to((subject.id,))


@pytest.mark.parametrize("field", ["include", "exclude"])
@pytest.mark.parametrize("selector", ["skills/alpha/SKILL.md", "fixture"])
def test_hard_case_path_selector_rejected(
    selection_inventory: Inventory, field: str, selector: str
) -> None:
    """Paths cannot be used as capability identities or partial file filters."""
    result = plan(selection_inventory, **{field: (selector,)})
    assert_that([item.code for item in errors(result)]).contains(
        "selection.invalid-selector"
    )


def test_hard_case_missing_required_resource_fails_closed(
    selection_inventory: Inventory,
) -> None:
    """A truncated ingest must fail rather than silently omit shared bytes."""
    result = plan(
        replace(selection_inventory, resources=()), include=(PREFIX + "beta",)
    )
    assert_that(errors(result)[0].code).is_equal_to("selection.required-missing")
    assert_that(errors(result)[0].chain).is_equal_to((PREFIX + "beta", RESOURCE))
    assert_that(errors(result)[0].fix).contains("mapping/ingest")


def test_hard_case_path_display_rename_preserves_id_and_explicit_migration(
    selection_inventory: Inventory,
) -> None:
    """Path moves keep IDs; ID moves fail old selectors until explicitly migrated."""
    moved = change(
        selection_inventory, "beta", source_path=PurePosixPath("skills/new-display")
    )
    assert_that(selected(plan(moved, include=(PREFIX + "beta",)))).contains(
        PREFIX + "beta"
    )
    renamed = change(moved, "beta", id=CapabilityId.parse(PREFIX + "new-id"))
    assert_that(
        [item.code for item in errors(plan(renamed, include=(PREFIX + "beta",)))]
    ).contains("selection.selector-unmatched")
    result = plan(
        renamed,
        include=(PREFIX + "beta",),
        overrides=Overrides(
            migrations=(Migration(from_=PREFIX + "beta", to=PREFIX + "new-id"),)
        ),
    )
    assert_that(selected(result)).contains(PREFIX + "new-id")


def test_shortest_deterministic_chain_and_fix(selection_inventory: Inventory) -> None:
    """BFS picks the shortest path and a stable tie even if input order changes."""
    result = plan(
        selection_inventory, include=(PREFIX + "alpha",), exclude=(PREFIX + "target",)
    )
    finding = errors(result)[0]
    assert_that(finding.chain).is_equal_to(
        tuple(PREFIX + name for name in ("alpha", "short", "target"))
    )
    shuffled = replace(
        selection_inventory,
        capabilities=tuple(reversed(selection_inventory.capabilities)),
    )
    assert_that(
        plan(
            shuffled, include=(PREFIX + "alpha",), exclude=(PREFIX + "target",)
        ).to_json()
    ).is_equal_to(result.to_json())
    assert_that(explain(result)).contains("chain:", "fix:", "exclude")


def test_unmatched_exclude_cannot_silently_let_content_back_in(
    selection_inventory: Inventory,
) -> None:
    """A stale explicit veto is an error even when every include remains valid."""
    result = plan(selection_inventory, exclude=(PREFIX + "removed-upstream-id",))
    assert_that(result.valid).is_false()
    assert_that([item.code for item in errors(result)]).contains(
        "selection.selector-unmatched"
    )


def test_two_dangling_directions_are_recorded_once(
    selection_inventory: Inventory,
) -> None:
    """Every retained source-to-missing-target edge has its own warning."""
    from ai_skills_engine.inventory.capability_id import CapabilityId

    graph = change(
        selection_inventory, "beta", related=(CapabilityId.parse(PREFIX + "target"),)
    )
    graph = change(graph, "alpha", related=(CapabilityId.parse(PREFIX + "target"),))
    result = plan(
        graph, include=(PREFIX + "alpha", PREFIX + "beta"), exclude=(PREFIX + "target",)
    )
    assert_that(result.dangling_related).is_equal_to(
        ((PREFIX + "alpha", PREFIX + "target"), (PREFIX + "beta", PREFIX + "target"))
    )
    assert_that(
        [item.code for item in result.diagnostics].count("selection.dangling-related")
    ).is_equal_to(2)


def test_public_default_selection_and_invalid_collision_override(
    selection_inventory: Inventory,
) -> None:
    """Pure default resolution selects all; stale collision decisions fail closed."""
    from ai_skills_engine.manifest.collision import Collision
    from ai_skills_engine.selection import select

    assert_that(len(selected(select(selection_inventory)))).is_equal_to(
        len(selection_inventory.capabilities)
    )
    result = plan(
        selection_inventory,
        overrides=Overrides(
            collisions=(Collision(capability=PREFIX + "absent", action="skip"),)
        ),
    )
    assert_that([item.code for item in errors(result)]).contains(
        "selection.invalid-collision-override"
    )


def test_explicit_package_migrations_chain_and_cycles(
    selection_inventory: Inventory,
) -> None:
    """Declared package moves compose, while migration loops fail deterministically."""
    migrated = plan(
        selection_inventory,
        include=("old/tools:skill/beta",),
        overrides=Overrides(
            migrations=(
                Migration(from_="old/tools", to="intermediate/tools"),
                Migration(from_="intermediate/tools", to="fixture/tools"),
            )
        ),
    )
    assert_that(selected(migrated)).is_equal_to({PREFIX + "beta"})
    cyclic = plan(
        selection_inventory,
        include=(PREFIX + "beta",),
        overrides=Overrides(
            migrations=(
                Migration(from_="fixture/tools", to="old/tools"),
                Migration(from_="old/tools", to="fixture/tools"),
            )
        ),
    )
    assert_that([item.code for item in errors(cyclic)]).contains(
        "selection.invalid-selector"
    )
    assert_that(errors(cyclic)[0].fix).contains("cyclic migrations")


@pytest.mark.parametrize(
    ("selector", "denied"),
    [
        ("github.com/fixture/x", True),
        ("github.com/fixture/*", True),
        ("github.com/fix*", True),
        ("fixture/x", False),
        ("github.com/Fixture/x", False),
        ("https://github.com/fixture/x", False),
        ("github.com/fixture/x.git", False),
    ],
    ids=[
        "exact",
        "owner-wildcard",
        "raw-prefix",
        "shorthand",
        "case",
        "url",
        "git-suffix",
    ],
)
def test_origin_deny_matches_documented_semantics(selector: str, denied: bool) -> None:
    """Origin denies are exact or raw-prefix locator matches, never normalized."""
    match = denied_origin(
        origins=["github.com/fixture/x"],
        policy=Policy(deny=Deny(origins=(selector,))),
    )
    assert_that(match is not None).is_equal_to(denied)


@pytest.mark.parametrize(
    ("graph", "verb"),
    [
        ({"a": {"requires": ["c"]}, "c": {}}, "requires"),
        (
            {"a": {"requires": ["b"]}, "b": {"requires": ["c"]}, "c": {}},
            "transitively requires",
        ),
    ],
    ids=["direct", "transitive"],
)
def test_required_veto_message_names_transitive_requirements(
    graph: dict[str, dict[str, list[str]]], verb: str
) -> None:
    """A blocked requirement reached through another capability says so."""
    inventory = inventory_graph({"capabilities": graph})
    result = plan(inventory, include=(PREFIX + "a",), exclude=(PREFIX + "c",))
    messages = [
        item.message
        for item in result.diagnostics
        if item.code == "selection.required-excluded"
    ]
    assert_that(messages).is_length(1)
    assert_that(messages[0]).starts_with(f"{PREFIX}a {verb} {PREFIX}c, ")


def test_rejected_candidate_explanation_marks_the_invalid_plan() -> None:
    """A rejected payload kept as a candidate is not explained as a clean pick."""
    inventory = inventory_graph({"capabilities": {"a": {"requires": ["broken"]}}})
    inventory = replace(
        inventory,
        rejected=(CapabilityId.parse(PREFIX + "broken"),),
        diagnostics=(
            *inventory.diagnostics,
            Diagnostic("inventory.invalid-payload", PREFIX + "broken", "bad bytes"),
        ),
    )
    result = select(inventory)
    broken = next(item for item in result.capabilities if item.id == PREFIX + "broken")
    assert_that(result.valid).is_false()
    assert_that(broken.reason).ends_with("payload rejected by inventory (plan invalid)")
    healthy = next(item for item in result.capabilities if item.id == PREFIX + "a")
    assert_that(healthy.reason).does_not_contain("payload rejected")


def test_explain_indents_multi_line_diagnostic_messages() -> None:
    """Continuation lines of a message stay inside its diagnostic block."""
    inventory = inventory_graph({"capabilities": {"a": {}}})
    inventory = replace(
        inventory,
        diagnostics=(
            Diagnostic("inventory.invalid-payload", PREFIX + "a", "line one\nline two"),
        ),
    )
    text = explain(select(inventory))
    assert_that(text).contains(
        "error[inventory.invalid-payload]: line one\n  line two\n"
    )


@pytest.mark.parametrize(
    ("selector", "identity", "expected"),
    [
        ("vendor/tools*", "vendor/tools-extra:skill/x", True),
        ("vendor/tools", "vendor/tools-extra:skill/x", False),
        ("vendor/tools", "vendor/tools:skill/x", True),
        ("vendor/*", "vendor/other:skill/x", True),
        ("vendor/tools:skill/x", "vendor/tools:skill/x", True),
    ],
    ids=["raw-prefix", "package-boundary", "package", "publisher", "exact"],
)
def test_selector_matching_documented_semantics(
    selector: str, identity: str, expected: bool
) -> None:
    """A trailing ``*`` is a raw prefix; a package selector keeps its boundary."""
    assert_that(matches(selector=selector, identity=identity)).is_equal_to(expected)
