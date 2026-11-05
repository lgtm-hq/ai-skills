"""Diagnostic dependency chains walked over embedded direct edges.

The walk explains a closure violation; it never decides one. Membership is
decided by the precomputed closure alone.
"""

from collections import deque

from ai_skills_engine.install.inventory import Inventory


def _holds(inventory: Inventory, capability: str, target: str) -> bool:
    """Report whether a capability directly reaches a target.

    Args:
        inventory: Merged inventory.
        capability: Capability on the walk.
        target: Capability or resource ID sought.

    Returns:
        True when the capability is the target or embeds the target resource.
    """
    record = inventory.capabilities[capability]
    return capability == target or any(
        item["id"] == target for item in record["resources"]
    )


def dependency_chain(inventory: Inventory, start: str, target: str) -> tuple[str, ...]:
    """Find the shortest chain of ``requires`` edges from a capability to a target.

    Args:
        inventory: Merged inventory.
        start: Kept capability.
        target: Removed capability or resource in its closure.

    Returns:
        IDs from ``start`` to ``target``; ``(start, target)`` if the embedded
        edges do not explain the closure entry.
    """
    parents: dict[str, str | None] = {start: None}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        if _holds(inventory, current, target):
            path = [current]
            while (parent := parents[path[-1]]) is not None:
                path.append(parent)
            path.reverse()
            return (*path, target) if path[-1] != target else tuple(path)
        for edge in sorted(inventory.capabilities[current]["requires"]):
            if edge in inventory.capabilities and edge not in parents:
                parents[edge] = current
                queue.append(edge)
    return (start, target)
