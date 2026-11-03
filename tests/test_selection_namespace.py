"""Catalog collisions, persisted aliases/skips and policy precedence."""

from dataclasses import replace
from typing import Literal

import pytest
from assertpy import assert_that
from selection_helpers import PREFIX, change, errors, inventory_graph, plan, selected

from ai_skills_engine.inventory.model import CapabilityId, Inventory, PackageId, Role
from ai_skills_engine.manifest.collision import Collision
from ai_skills_engine.manifest.deny import Deny
from ai_skills_engine.manifest.overrides import Overrides
from ai_skills_engine.manifest.policy import Policy

pytest_plugins = ["selection_helpers"]


@pytest.fixture
def colliding_inventory() -> Inventory:
    """Two publishers author identical catalog bytes at the same destination.

    Returns:
        Inventory whose IDs differ but destination name/hash agree.
    """
    graph = inventory_graph({"capabilities": {"same": {}}})
    second = replace(
        graph.capabilities[0],
        id=CapabilityId.parse("second/tools:skill/same"),
        package=PackageId.parse("second/tools"),
        origin="github.com/second/catalog",
    )
    return replace(graph, capabilities=(*graph.capabilities, second))


def test_catalog_identical_bytes_still_require_collision_resolution(
    colliding_inventory: Inventory,
) -> None:
    """Hash equality cannot erase distinct catalog namespace ownership."""
    result = plan(colliding_inventory)
    assert_that(result.valid).is_false()
    assert_that(errors(result)[0].code).is_equal_to("selection.namespace-collision")
    assert_that(result.namespace).is_equal_to(
        (("skill", "same", (PREFIX + "same", "second/tools:skill/same")),)
    )


@pytest.mark.parametrize("action", ["rename", "skip"])
def test_persisted_collision_rename_or_skip_resolves_noninteractively(
    colliding_inventory: Inventory, action: str
) -> None:
    """Both supported declarations yield deterministic valid replayable plans."""
    result = plan(
        colliding_inventory,
        overrides=Overrides(
            collisions=(
                Collision(
                    capability="second/tools:skill/same",
                    action=action,
                    name="other" if action == "rename" else None,
                ),
            )
        ),
    )
    assert_that(result.valid).is_true()
    assert_that(selected(result)).contains(PREFIX + "same")
    other = next(item for item in result.capabilities if item.id.startswith("second/"))
    assert_that(other.state).is_equal_to("excluded" if action == "skip" else "selected")
    if action == "rename":
        assert_that(other.names).is_equal_to(("other",))


def test_declared_alias_reserved_even_when_owner_not_selected(
    selection_inventory: Inventory,
) -> None:
    """A later import cannot take an earlier owner's excluded persistent alias."""
    graph = change(selection_inventory, "beta", aliases=("alpha",))
    result = plan(graph, include=(PREFIX + "alpha",))
    assert_that(errors(result)[0].code).is_equal_to("selection.namespace-collision")
    assert_that(errors(result)[0].message).contains(PREFIX + "beta", PREFIX + "alpha")
    assert_that(selected(result)).does_not_contain(PREFIX + "beta")


def test_override_alias_is_reserved_before_selection(
    selection_inventory: Inventory,
) -> None:
    """A persisted rename reserves its destination even with no selected owner."""
    result = plan(
        selection_inventory,
        include=(PREFIX + "alpha",),
        overrides=Overrides(
            collisions=(
                Collision(capability=PREFIX + "beta", action="rename", name="alpha"),
            )
        ),
    )
    assert_that([item.code for item in errors(result)]).contains(
        "selection.namespace-collision"
    )


def test_skip_of_required_capability_fails(selection_inventory: Inventory) -> None:
    """Collision skip is a veto and cannot silently amputate a dependency."""
    result = plan(
        selection_inventory,
        include=(PREFIX + "alpha",),
        overrides=Overrides(
            collisions=(Collision(capability=PREFIX + "target", action="skip"),)
        ),
    )
    assert_that([item.code for item in errors(result)]).contains(
        "selection.required-excluded"
    )


def test_deny_wins_over_include_exclude_and_rename(
    selection_inventory: Inventory,
) -> None:
    """Deny is evaluated on source evidence and is never waived by a rename."""
    graph = change(selection_inventory, "target", origin="blocked")
    result = plan(
        graph,
        include=(PREFIX + "alpha",),
        exclude=(PREFIX + "target",),
        policy=Policy(deny=Deny(origins=("blocked",))),
        overrides=Overrides(
            collisions=(
                Collision(
                    capability=PREFIX + "target", action="rename", name="safe-name"
                ),
            )
        ),
    )
    target = next(item for item in result.capabilities if item.id == PREFIX + "target")
    assert_that(target.state).is_equal_to("denied")
    assert_that(errors(result)[0].code).is_equal_to("selection.required-denied")


def test_policy_role_eligibility_is_explained(selection_inventory: Inventory) -> None:
    """Disallowed roles are reported as unsupported rather than selected."""
    result = plan(selection_inventory, policy=Policy(roles=()))
    assert_that({item.state for item in result.capabilities}).is_equal_to(
        {"unsupported"}
    )
    assert_that(selected(result)).is_empty()


@pytest.mark.parametrize("role", [Role.INTEGRATION, Role.LIFECYCLE, Role.SKILL])
@pytest.mark.parametrize("multiple", [False, True])
@pytest.mark.parametrize("aliases", [(), ("renamed",)])
@pytest.mark.parametrize("excluded", [False, True])
def test_typed_alias_boundary_preserves_configuration_key_ownership(
    role: Role, multiple: bool, aliases: tuple[str, ...], excluded: bool
) -> None:
    """Public typed inventories cannot erase multi-key ownership through aliases."""
    graph = inventory_graph({"capabilities": {"first": {}, "second": {}}})
    first = replace(
        graph.capabilities[0],
        id=CapabilityId.parse(f"fixture/tools:{role}/first"),
        role=role,
        destination_names=("alpha", "beta") if multiple else ("beta",),
        aliases=aliases,
    )
    second = replace(
        graph.capabilities[1],
        id=CapabilityId.parse(f"fixture/tools:{role}/second"),
        role=role,
        destination_names=("beta",),
    )
    result = plan(
        replace(graph, capabilities=(first, second)),
        exclude=(str(first.id),) if excluded else (),
    )
    invalid_alias = bool(aliases) and multiple and role != Role.SKILL
    conflict = invalid_alias or (not aliases and not excluded)
    assert_that(result.valid).is_equal_to(not conflict)
    if invalid_alias:
        assert_that([item.code for item in errors(result)]).contains(
            "selection.invalid-alias", "selection.namespace-collision"
        )
        beta = next(
            item for item in result.namespace if item[:2] == (str(role), "beta")
        )
        assert_that(beta[2]).contains(str(first.id), str(second.id))
    elif aliases:
        entry = next(item for item in result.capabilities if item.id == str(first.id))
        assert_that(entry.names).is_equal_to(aliases)


@pytest.mark.parametrize("role", [Role.INTEGRATION, Role.LIFECYCLE, Role.SKILL])
def test_single_key_alias_stays_reserved_when_excluded(role: Role) -> None:
    """Ordinary and single-key configuration aliases reserve names before selection."""
    graph = inventory_graph({"capabilities": {"first": {}, "second": {}}})
    capabilities = tuple(
        replace(
            item,
            id=CapabilityId.parse(f"fixture/tools:{role}/{item.id.name}"),
            role=role,
            destination_names=("beta",),
            aliases=("beta",) if item.id.name == "first" else (),
        )
        for item in graph.capabilities
    )
    result = plan(
        replace(graph, capabilities=capabilities),
        exclude=(str(capabilities[0].id),),
    )
    assert_that(result.valid).is_false()
    assert_that(errors(result)[0].code).is_equal_to("selection.namespace-collision")


@pytest.mark.parametrize("action", ["rename", "skip"])
@pytest.mark.parametrize("duplicate", [False, True])
def test_collision_decisions_use_publisher_migration_map(
    colliding_inventory: Inventory, action: Literal["rename", "skip"], duplicate: bool
) -> None:
    """The public boundary replays publisher migrations and rejects coalesced IDs."""
    previous = "old/tools:skill/same"
    current = "second/tools:skill/same"
    decision = Collision(
        capability=previous,
        action=action,
        name="renamed" if action == "rename" else None,
    )
    result = plan(
        colliding_inventory,
        overrides=Overrides(
            collisions=(
                (decision, replace(decision, capability=current))
                if duplicate
                else (decision,)
            )
        ),
        migrations={"old/tools": "second/tools"},
    )
    assert_that(result.valid).is_equal_to(not duplicate)
    if duplicate:
        finding = next(
            item
            for item in errors(result)
            if item.code == "selection.invalid-collision-override"
        )
        assert_that(finding.location).is_equal_to(current)
        assert_that(finding.message).contains("duplicated")
