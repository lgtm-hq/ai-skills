"""Consumer locator matching shared by lineage validation and selection."""

from collections.abc import Iterable

from ai_skills_engine.manifest.policy import Policy


def denied_origin(
    *, origins: Iterable[str], policy: Policy | None
) -> tuple[str, str] | None:
    """Match only origin locators, never publisher short names or equal hashes.

    Args:
        origins: Declared origin locators in deterministic chain order.
        policy: Final consumer's origin vetoes.

    Returns:
        Origin and matching selector, or no match.
    """
    selectors = sorted(policy.deny.origins if policy and policy.deny else ())
    for origin in origins:
        for selector in selectors:
            if origin == selector or (
                selector.endswith("*") and origin.startswith(selector[:-1])
            ):
                return origin, selector
    return None
