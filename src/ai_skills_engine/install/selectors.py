"""Consumer exclude selectors and origin deny rules over qualified IDs only."""

import re
from dataclasses import dataclass
from enum import StrEnum, auto

from ai_skills_engine.install.errors import InstallError

_SEGMENT = r"[a-z0-9]+(?:-[a-z0-9]+)*"
PACKAGE_ID = re.compile(rf"{_SEGMENT}/{_SEGMENT}")
CAPABILITY_ID = re.compile(
    rf"{_SEGMENT}/{_SEGMENT}:"
    rf"(?:skill|instruction|specialist|workflow|lifecycle|integration)/{_SEGMENT}"
)


class SelectorKind(StrEnum):
    """What an exclude selector removes."""

    CAPABILITY = auto()
    PACKAGE = auto()


@dataclass(frozen=True, order=True)
class Selector:
    """One exclude: a qualified capability or package ID.

    Attributes:
        kind: Capability or package.
        id: Qualified ID; never a path, alias or content hash.
    """

    kind: SelectorKind
    id: str

    def __str__(self) -> str:
        """Render the CLI spelling.

        Returns:
            ``kind:id``.
        """
        return f"{self.kind}:{self.id}"


@dataclass(frozen=True, order=True)
class DenyRule:
    """One origin deny and where it came from.

    Attributes:
        origin: Exact origin locator, or a prefix ending in ``*``.
        source: Input that supplied it, such as ``profile`` or ``--deny-origin``.
    """

    origin: str
    source: str


def make_selector(kind: SelectorKind, value: str) -> Selector:
    """Validate a qualified ID for its selector kind.

    Args:
        kind: Selector kind.
        value: Qualified ID.

    Returns:
        Validated selector.

    Raises:
        InstallError: If the ID does not match the kind's qualified form.
    """
    pattern = CAPABILITY_ID if kind is SelectorKind.CAPABILITY else PACKAGE_ID
    if not pattern.fullmatch(value):
        raise InstallError(f"invalid {kind} ID {value!r}")
    return Selector(kind=kind, id=value)


def parse_selector(text: str) -> Selector:
    """Parse ``capability:<id>`` or ``package:<id>``.

    Args:
        text: CLI spelling.

    Returns:
        Validated selector.

    Raises:
        InstallError: For another kind or a malformed ID.
    """
    kind, separator, value = text.partition(":")
    if not separator or kind not in {item.value for item in SelectorKind}:
        raise InstallError(
            f"invalid exclude {text!r}; use capability:<publisher/package:role/name> "
            "or package:<publisher/package>"
        )
    return make_selector(SelectorKind(kind), value)


def parse_origin(text: str) -> str:
    """Validate an origin deny value.

    Args:
        text: Origin locator such as ``github.com/example/vendor``.

    Returns:
        The unchanged origin.

    Raises:
        InstallError: If the value is empty or contains whitespace.
    """
    if not text or any(char.isspace() for char in text):
        raise InstallError(f"invalid origin {text!r}")
    return text
