"""Host-specific source data and conservative projection rules."""

from dataclasses import dataclass

_RULES = frozenset({"preserve", "refuse", "unverified"})


def valid_rule(rule: object) -> bool:
    """Tell whether a projection rule is defined; ``drop`` never is.

    Args:
        rule: Declared rule value.

    Returns:
        True for ``preserve``, ``refuse``, ``unverified`` or a trimmed ``map:<x>``.
    """
    return isinstance(rule, str) and (
        rule in _RULES
        or (
            rule.startswith("map:")
            and bool(rule[4:].strip())
            and rule[4:] == rule[4:].strip()
        )
    )


@dataclass(frozen=True)
class HostAttribute:
    """A source value retained as canonical JSON and explicit per-host rules."""

    key: str
    value_json: str
    semantics: str
    hosts: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        """Reject invalid rules even for callers constructing records directly."""
        names = [host for host, _ in self.hosts]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate host rule")
        for _, rule in self.hosts:
            if not valid_rule(rule):
                raise ValueError(f"Invalid projection rule: {rule}; drop is forbidden")

    def rule_for(self, host: str, *, strict: bool = True) -> str:
        """Report a rule without projecting or certifying host behavior.

        Args:
            host: Destination product/interface name.
            strict: Treat uncertainty as refusal.

        Returns:
            Declared rule, or refusal for an unknown host or strict uncertainty.
        """
        rule = dict(self.hosts).get(host, "unverified")
        return "refuse" if strict and rule == "unverified" else rule
