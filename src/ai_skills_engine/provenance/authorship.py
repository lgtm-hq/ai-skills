"""Published authorship statement without consumer authority."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Authorship:
    """An independently authored claim; only the final consumer can accept it."""

    capability: str
    path: str
    reason: str
    independently_authored: Literal[True] = True
