"""Evidence for one consumer deny."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DenyMatch:
    """Matched ancestor origin, declaration and resource path if applicable."""

    origin: str
    selector: str
    chain: tuple[str, ...]
