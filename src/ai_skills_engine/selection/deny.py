"""Single consumer deny entry point, independent of aliases and content hashes."""

from ai_skills_engine.manifest.policy import Policy
from ai_skills_engine.selection.deny_match import DenyMatch
from ai_skills_engine.selection.deny_subject import DenySubject


def deny_matches(capability: DenySubject, policy: Policy | None) -> DenyMatch | None:
    """Match immediate/ancestor origins, including the required resource lineage.

    Args:
        capability: Inventory identity with its bound resources and lineage.
        policy: Consumer policy only; publishers cannot grant exceptions.

    Returns:
        Deterministic matching evidence, or None. Independent equal bytes have
        no effect: only explicitly supplied origins participate.
    """
    origins = policy.deny.origins if policy and policy.deny else ()
    for origin in (capability.origin, *capability.lineage):
        for selector in sorted(origins):
            if origin == selector or (
                selector.endswith("*") and origin.startswith(selector[:-1])
            ):
                return DenyMatch(
                    origin=origin, selector=selector, chain=(capability.id,)
                )
    for resource in sorted(capability.resources, key=lambda item: item.id):
        match = deny_matches(capability=resource, policy=policy)
        if match:
            return DenyMatch(
                origin=match.origin,
                selector=match.selector,
                chain=(capability.id, *match.chain),
            )
    return None
