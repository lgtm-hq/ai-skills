"""Public selection states."""

from enum import StrEnum, auto


class State(StrEnum):
    """Disposition of every observed capability and resource."""

    SELECTED = auto()
    PULLED_IN = "pulled-in"
    EXCLUDED = auto()
    DENIED = auto()
    UNSUPPORTED = auto()
