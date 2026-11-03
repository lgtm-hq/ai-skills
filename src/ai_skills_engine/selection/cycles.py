"""Iterative Tarjan SCC pass: O(vertices + edges), without recursion limits."""

from collections.abc import Iterator, Mapping


def strongly_connected(
    graph: Mapping[str, tuple[str, ...]],
) -> tuple[tuple[str, ...], ...]:
    """Partition a requires graph in one pass, including singleton components.

    Args:
        graph: Qualified capability IDs and direct requirements.

    Returns:
        Components in deterministic traversal order. Each edge is visited once;
        display sorting belongs to the explain layer.
    """
    indexes: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    result: list[tuple[str, ...]] = []
    frames: list[tuple[str, Iterator[str]]] = []

    def enter(node: str) -> None:
        """Push one DFS frame and one Tarjan stack record."""
        indexes[node] = low[node] = len(indexes)
        stack.append(node)
        active.add(node)
        frames.append((node, iter(graph.get(node, ()))))

    for start in graph:
        if start in indexes:
            continue
        enter(start)
        while frames:
            node, edges = frames[-1]
            target = next(edges, None)
            if target is not None:
                if target not in indexes:
                    enter(target)
                elif target in active:
                    low[node] = min(low[node], indexes[target])
                continue
            frames.pop()
            if low[node] == indexes[node]:
                members = []
                while True:
                    member = stack.pop()
                    active.remove(member)
                    members.append(member)
                    if member == node:
                        break
                result.append(tuple(members))
            if frames:
                parent = frames[-1][0]
                low[parent] = min(low[parent], low[node])
    return tuple(result)
