"""Origin denies over embedded lineage, at any re-export depth.

A deny matches an origin anywhere in any lineage chain: the first publisher,
any intermediate re-exporter or the last hop. Later hops cannot clear an
earlier match. Rules can come from any input (CLI, profile, and later org
policy); each carries its source for diagnostics.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ai_skills_engine.install.errors import InstallError
from ai_skills_engine.install.selectors import DenyRule


@dataclass(frozen=True)
class DenyHit:
    """Evidence that a subject derives from a denied origin.

    Attributes:
        origin: Matching origin found in the lineage.
        rule: The deny rule that matched.
    """

    origin: str
    rule: DenyRule

    def reason(self) -> str:
        """Describe the hit for removal reports.

        Returns:
            Human-readable reason naming the rule's source.
        """
        return f"denied origin {self.origin} ({self.rule.source} {self.rule.origin})"


def origin_matches(origin: str, rule: str) -> bool:
    """Match one origin locator against a rule.

    Args:
        origin: Declared lineage origin.
        rule: Exact locator or a prefix ending in ``*``.

    Returns:
        Whether the rule covers the origin.
    """
    return origin == rule or (rule.endswith("*") and origin.startswith(rule[:-1]))


def lineage_origins(
    chains: Sequence[Mapping[str, Any]], *, subject: str
) -> tuple[str, ...]:
    """Collect every origin from every lineage chain of one subject.

    Args:
        chains: Index ``lineage`` records.
        subject: Capability or resource ID for diagnostics.

    Returns:
        Origins in chain order.

    Raises:
        InstallError: If lineage is missing or a chain has no hops (fail closed).
    """
    origins = tuple(
        str(hop.get("origin") or "")
        for chain in chains
        for hop in chain.get("lineage") or ()
    )
    if not chains or any(not chain.get("lineage") for chain in chains):
        raise InstallError(f"{subject}: missing lineage; cannot evaluate origin denies")
    if any(not origin for origin in origins):
        raise InstallError(f"{subject}: lineage hop without an origin")
    return origins


def denied(
    chains: Sequence[Mapping[str, Any]], *, subject: str, rules: Iterable[DenyRule]
) -> DenyHit | None:
    """Find the first denied origin in a subject's lineage.

    Args:
        chains: Index ``lineage`` records.
        subject: Capability or resource ID.
        rules: Deny rules from every source.

    Returns:
        The first match in chain order, or None.
    """
    ordered = sorted(rules)
    for origin in lineage_origins(chains, subject=subject):
        for rule in ordered:
            if origin_matches(origin, rule.origin):
                return DenyHit(origin=origin, rule=rule)
    return None
