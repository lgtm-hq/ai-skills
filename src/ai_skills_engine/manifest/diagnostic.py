"""Machine-readable validation findings."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnostic:
    """One finding at a JSON-pointer location; warnings do not reject input."""

    code: str
    location: str
    message: str
    warning: bool = False
