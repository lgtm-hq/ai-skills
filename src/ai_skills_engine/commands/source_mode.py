"""How a command may obtain pinned vendor sources."""

from enum import StrEnum, auto


class SourceMode(StrEnum):
    """Source acquisition authority of one command.

    Attributes:
        RESOLVE: ``lock``: re-resolve changed pins and fetch missing sources;
            never move an unchanged pin's locked digest.
        FETCH: ``lock --fetch``: fill the cache for the existing lock only.
        FROZEN: ``lock --check``/``build``: cache only, no network, no writes.
    """

    RESOLVE = auto()
    FETCH = auto()
    FROZEN = auto()
