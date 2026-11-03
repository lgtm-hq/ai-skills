"""Breadth-first closure with deterministic shortest dependency witnesses."""

from collections import deque
from collections.abc import Iterable, Mapping


def closure(
    *, graph: Mapping[str, tuple[str, ...]], roots: Iterable[str], blocked: set[str]
) -> dict[str, str | None]:
    """Visit each reachable edge once, retaining blocked endpoints as evidence.

    Args:
        graph: Sorted direct capability/resource edges.
        roots: Explicit or default roots.
        blocked: Excludes, direct denies and unsupported capabilities.

    Returns:
        Node to predecessor mapping. Blocked targets are never expanded.
    """
    parents: dict[str, str | None] = dict.fromkeys(sorted(set(roots)))
    queue = deque(parents)
    while queue:
        node = queue.popleft()
        if node in blocked:
            continue
        for target in graph.get(node, ()):
            if target not in parents:
                parents[target] = node
                queue.append(target)
    return parents


def dependency_chain(
    *, parents: Mapping[str, str | None], target: str
) -> tuple[str, ...]:
    """Reconstruct a shortest witness only when rendering an entry or finding.

    Args:
        parents: Breadth-first predecessor map.
        target: Reached endpoint.

    Returns:
        Root-to-target chain; empty for unreachable nodes.
    """
    if target not in parents:
        return ()
    chain = [target]
    while (parent := parents[chain[-1]]) is not None:
        chain.append(parent)
    return tuple(reversed(chain))
