"""Internal recursion state, always carrying the final consumer's policy."""

from dataclasses import dataclass

from ai_skills_engine.manifest.policy import Policy
from ai_skills_engine.provenance.authorship import Authorship


@dataclass(frozen=True)
class Context:
    """Pinned publication identity and visited repository/revision pairs."""

    origin: str
    rev: str | None
    policy: Policy | None
    ancestors: tuple[tuple[str, str | None], ...] = ()
    attestations: tuple[Authorship, ...] = ()
    migrations: tuple[tuple[str, str], ...] = ()


def origin_locator(value: str) -> str:
    """Normalize shorthand GitHub repos without changing qualified locators.

    Args:
        value: Publisher repository or vendor locator.

    Returns:
        Locator suitable for exact consumer deny matching.
    """
    return (
        "github.com/" + value if value.count("/") == 1 and ":" not in value else value
    )
