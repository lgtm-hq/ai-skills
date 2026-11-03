"""Property-based closure and veto controls, plus iterative SCC scalability."""

from collections.abc import Iterator

import pytest
from assertpy import assert_that
from hypothesis import example, given, settings
from hypothesis import strategies as st
from selection_helpers import PREFIX, errors, inventory_graph, plan, selected

from ai_skills_engine.selection import cycles
from ai_skills_engine.selection.closure import closure, dependency_chain
from ai_skills_engine.selection.cycles import strongly_connected

GRAPH = st.lists(
    st.sets(st.integers(min_value=0, max_value=11)), min_size=12, max_size=12
)
NODES = st.sets(st.integers(min_value=0, max_value=11))


@given(edges=GRAPH, roots=NODES)
@settings(max_examples=100, deadline=1000)
def test_property_closure_is_idempotent(edges: list[set[int]], roots: set[int]) -> None:
    """Expanding a graph's closure again cannot change retained membership."""
    graph = {
        str(index): tuple(sorted(map(str, targets)))
        for index, targets in enumerate(edges)
    }
    first = closure(graph=graph, roots=map(str, roots), blocked=set())
    second = closure(graph=graph, roots=first, blocked=set())
    assert_that(set(second)).is_equal_to(set(first))


@given(edges=GRAPH, roots=NODES, excluded=NODES)
@example(edges=[{1}, *[set() for _ in range(11)]], roots={0}, excluded={1})
@settings(max_examples=100, deadline=1000)
def test_property_exclude_precedence_across_random_graphs(
    edges: list[set[int]], roots: set[int], excluded: set[int]
) -> None:
    """No include or expansion overrides exclusions; blocked reachable edges fail."""
    names = ["node-" + chr(ord("a") + index) for index in range(12)]
    inventory = inventory_graph(
        {
            "capabilities": {
                names[index]: {
                    "requires": [names[target] for target in sorted(targets)]
                }
                for index, targets in enumerate(edges)
            }
        }
    )
    denied = {PREFIX + names[index] for index in excluded}
    result = plan(
        inventory,
        include=tuple(PREFIX + names[index] for index in roots),
        exclude=tuple(denied),
    )
    assert_that(selected(result).intersection(denied)).is_empty()
    graph = {
        PREFIX
        + names[index]: tuple(PREFIX + names[target] for target in sorted(targets))
        for index, targets in enumerate(edges)
    }
    expected = closure(
        graph=graph,
        roots={PREFIX + names[index] for index in roots} - denied,
        blocked=denied,
    )
    assert_that(selected(result)).is_equal_to(set(expected) - denied)
    assert_that(bool(errors(result))).is_equal_to(bool(set(expected) & denied))


def test_shortest_chain_uses_lexicographic_tie_break() -> None:
    """Sorted BFS uses the lexicographically first equally short root path."""
    graph = {"a": ("b", "c"), "b": ("z",), "c": ("z",)}
    parents = closure(graph=graph, roots=("a",), blocked={"z"})
    assert_that(dependency_chain(parents=parents, target="z")).is_equal_to(
        ("a", "b", "z")
    )


@pytest.mark.timeout(3)
def test_scc_pass_visits_each_edge_once_without_recursion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A large SCC stays linear and cannot hit Python's recursive DFS limit."""
    visits: list[str] = []

    def counted_edges(values: tuple[str, ...]) -> Iterator[str]:
        """Count visits to adjacency edges without altering graph membership."""
        for target in values:
            visits.append(target)
            yield target

    monkeypatch.setattr(cycles, "iter", counted_edges, raising=False)
    size = 10000
    graph = {str(index): (str((index + 1) % size),) for index in range(size)}
    components = strongly_connected(graph)
    assert_that(components).is_length(1)
    assert_that(components[0]).is_length(size)
    assert_that(visits).is_length(size)


def test_scc_separates_bridged_components_and_singletons() -> None:
    """Cross and back edges cannot accidentally fuse distinct SCCs."""
    graph = {
        "a": ("b",),
        "b": ("a", "c"),
        "c": ("d",),
        "d": ("c",),
        "e": (),
        "f": ("f",),
    }
    assert_that({frozenset(item) for item in strongly_connected(graph)}).is_equal_to(
        {
            frozenset(("a", "b")),
            frozenset(("c", "d")),
            frozenset(("e",)),
            frozenset(("f",)),
        }
    )
