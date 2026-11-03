"""Content and executable-mode observations without executing payload bytes."""

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class PayloadFile:
    """One regular file with canonical mode 0644 or owner-executable 0755.

    Paths are relative to the capability or resource root. Mode records Git-like
    executable identity, not the source's full POSIX permissions or execution
    authorization. Collection never runs the payload.
    """

    path: PurePosixPath
    sha256: str
    mode: int
