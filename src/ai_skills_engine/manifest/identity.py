"""Qualified identities and selectors shared by validation and callers."""

import re
from enum import StrEnum, auto
from typing import Literal


class Role(StrEnum):
    """Reserved capability roles in the v1 contract."""

    SKILL = auto()
    INSTRUCTION = auto()
    SPECIALIST = auto()
    WORKFLOW = auto()
    LIFECYCLE = auto()
    INTEGRATION = auto()


type Mode = Literal["native-plugin", "user-explode", "repo-materialize"]
type Transport = Literal["npm", "release-asset", "git-marketplace", "offline"]
SEGMENT = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_IDENTITY = re.compile(
    rf"(?P<publisher>{SEGMENT})/(?P<package>{SEGMENT})"
    rf"(?::(?P<role>{'|'.join(Role)}|resource)/(?P<name>{SEGMENT}))?\Z",
)


def matches(*, selector: str, identity: str) -> bool:
    """Match an exact qualified ID, package or validated trailing wildcard.

    A trailing ``*`` is a raw string prefix: ``vendor/tools*`` also matches
    ``vendor/tools-extra:skill/x``. A package selector matches its own
    ``package:`` members only. The ``selector + "/"`` arm serves bare
    publishers, which :func:`parse_id` rejects, so validated selectors never
    reach it; it is kept rather than widening or narrowing the grammar.

    Args:
        selector: Schema-validated manifest selector.
        identity: Exact capability or resource identity.

    Returns:
        Whether the declaration names this identity.
    """
    if selector.endswith("*"):
        return identity.startswith(selector[:-1])
    return identity == selector or identity.startswith((selector + ":", selector + "/"))


def parse_id(value: str, *, selector: bool = False) -> tuple[str, str, str, str]:
    """Parse an exact ID or a selector with one trailing wildcard.

    Args:
        value: Qualified package, capability or resource identity.
        selector: Permit a wildcard in the final package/name segment.

    Returns:
        Publisher, package, optional role and optional name.

    Raises:
        ValueError: If the input is a path, malformed ID or misplaced wildcard.
    """
    candidate = value
    wildcard = selector and value.endswith("*")
    if wildcard:
        candidate = value[:-1] + "wildcard"
    match = _IDENTITY.fullmatch(candidate)
    if match is None:
        raise ValueError(f"Invalid {'selector' if selector else 'ID'}: {value!r}")
    parts = tuple(
        match.group(name) or "" for name in ("publisher", "package", "role", "name")
    )
    publisher, package, role, name = parts
    if wildcard:
        if role:
            name = value.rsplit("/", 1)[1]
        else:
            package = value.split("/", 1)[1]
    return publisher, package, role, name
