"""Subtractive filtering: pure set membership over embedded artifact data.

``kept = inventory - excluded packages - excluded capabilities - denied
origins``. A kept capability whose precomputed closure (capabilities and
resources, including its own ``_shared/`` copies) meets the removed set fails
the whole selection. The result depends only on the inventory and the
selectors; nothing is resolved.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ai_skills_engine.install.chain import dependency_chain
from ai_skills_engine.install.deny import denied
from ai_skills_engine.install.errors import InstallError
from ai_skills_engine.install.inventory import Inventory
from ai_skills_engine.install.selectors import DenyRule, Selector, SelectorKind


@dataclass(frozen=True)
class Violation:
    """A kept capability that needs a removed capability or resource.

    Attributes:
        capability: Kept capability.
        target: Removed member of its closure.
        chain: Diagnostic path from ``capability`` to ``target``.
        reason: Why ``target`` was removed.
    """

    capability: str
    target: str
    chain: tuple[str, ...]
    reason: str


class ClosureError(InstallError):
    """The selection removes something a kept capability requires.

    The message renders every violation with its chain and the extra excludes
    that make the selection valid.

    Args:
        violations: Sorted violations.
    """

    def __init__(self, violations: tuple[Violation, ...]) -> None:
        self.violations = violations
        self.suggestions = tuple(
            sorted({f"capability:{item.capability}" for item in violations})
        )
        lines = ["selection removes what kept capabilities require:"]
        lines += [
            f"  {' -> '.join(item.chain)} ({item.target} {item.reason})"
            for item in violations
        ]
        lines.append("add these excludes to make the selection valid:")
        lines += [f"  --exclude {item}" for item in self.suggestions]
        super().__init__("\n".join(lines))


@dataclass(frozen=True)
class FilterResult:
    """Kept and removed IDs.

    Attributes:
        capabilities: Kept capability IDs, sorted.
        resources: Resource IDs in kept closures, sorted.
        removed: Removed capability and resource IDs with their reasons.
    """

    capabilities: tuple[str, ...]
    resources: tuple[str, ...]
    removed: Mapping[str, str]


def _removed(
    inventory: Inventory, excludes: frozenset[Selector], rules: tuple[DenyRule, ...]
) -> dict[str, str]:
    """Compute removed IDs and the first reason for each.

    Args:
        inventory: Merged inventory.
        excludes: Capability and package excludes.
        rules: Origin denies from every source.

    Returns:
        Removed capability and resource IDs mapped to reasons.
    """
    removed: dict[str, str] = {}
    for key, record in inventory.capabilities.items():
        package = Selector(kind=SelectorKind.PACKAGE, id=record["package"])
        capability = Selector(kind=SelectorKind.CAPABILITY, id=key)
        hit = denied(record["lineage"], subject=key, rules=rules)
        if capability in excludes or package in excludes:
            selector = capability if capability in excludes else package
            removed[key] = f"excluded by {selector}"
        elif hit is not None:
            removed[key] = hit.reason()
    for key, copies in inventory.copies.items():
        owner = inventory.resource_packages.get(key)
        hits = [denied(copy["lineage"], subject=key, rules=rules) for copy in copies]
        hit = next((item for item in hits if item is not None), None)
        if owner and Selector(kind=SelectorKind.PACKAGE, id=owner) in excludes:
            removed[key] = f"excluded by package:{owner}"
        elif hit is not None:
            removed[key] = hit.reason()
    return removed


def filter_inventory(
    inventory: Inventory, *, excludes: Iterable[Selector], denies: Iterable[DenyRule]
) -> FilterResult:
    """Subtract excludes and denies, then check every kept closure.

    Args:
        inventory: Merged, checked inventory.
        excludes: Capability and package excludes.
        denies: Origin denies from any source.

    Returns:
        Kept and removed sets.

    Raises:
        ClosureError: If a kept capability needs a removed ID.
    """
    removed = _removed(inventory, frozenset(excludes), tuple(sorted(set(denies))))
    kept = sorted(key for key in inventory.capabilities if key not in removed)
    violations = []
    for key in kept:
        capabilities, resources = inventory.closure(key)
        own = {item["id"] for item in inventory.capabilities[key]["resources"]}
        for target in sorted((capabilities | resources | own) & removed.keys()):
            violations.append(
                Violation(
                    capability=key,
                    target=target,
                    chain=dependency_chain(inventory, key, target),
                    reason=removed[target],
                )
            )
    if violations:
        raise ClosureError(tuple(violations))
    # Resources are delivered only as dependencies, as the builder selects them.
    needed = {item for key in kept for item in inventory.closure(key)[1]}
    return FilterResult(
        capabilities=tuple(kept),
        resources=tuple(sorted(needed)),
        removed=dict(sorted(removed.items())),
    )
