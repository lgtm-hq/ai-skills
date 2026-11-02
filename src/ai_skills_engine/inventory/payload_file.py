"""Content and executable-mode observations without executing payload bytes."""

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class PayloadFile:
    """One regular file relative to its capability or resource root."""

    path: PurePosixPath
    sha256: str
    mode: int
