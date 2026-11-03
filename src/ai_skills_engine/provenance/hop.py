"""One immutable publication step."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LineageHop:
    """Origin first, current publisher last; local revisions may be uncommitted."""

    origin: str
    publisher: str
    rev: str | None
    id: str
    path: str
    tree_digest: str
    renamed_from: str | None = None
    transforms: tuple[str, ...] = ()
