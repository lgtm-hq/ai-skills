"""Extension storage shared by frozen manifest records."""

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from types import MappingProxyType


@dataclass(frozen=True, kw_only=True)
class Record:
    """Preserve only explicitly prefixed extension keys outside named fields."""

    extensions: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze default mappings as well as supplied mapping containers."""
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, dict):
                object.__setattr__(self, item.name, MappingProxyType(value))
