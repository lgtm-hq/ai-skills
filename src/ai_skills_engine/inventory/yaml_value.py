"""Bounded, lossless JSON representation of supported YAML attribute values."""

import json
import math
from datetime import date, datetime
from typing import Any


def normalize_yaml_value(value: object) -> Any:
    """Preserve JSON values and encode YAML dates and typed mapping keys.

    ``$yaml`` is reserved: ordinary maps containing it are encoded as sorted
    key/value pairs too, so user data cannot collide with a tagged value.
    Non-string keys retain their JSON types instead of becoming object keys.
    Shared aliases expand as values within a finite budget; cycles are errors.

    Args:
        value: Parsed YAML attribute value.

    Returns:
        A deterministic, JSON-serializable representation.

    Raises:
        TypeError: On unsupported YAML value types.
        ValueError: On non-finite floats, cycles or exceeded traversal limits.
    """
    active: set[int] = set()
    remaining = 10000

    def visit(item: object, *, path: str, depth: int) -> Any:
        """Normalize one value, counting aliases again to bound expanded output."""
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            raise ValueError(f"{path}: YAML value exceeds node budget (10000)")
        if depth > 64:
            raise ValueError(f"{path}: YAML value exceeds depth limit (64)")
        if item is None or isinstance(item, (str, bool, int)):
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError(f"{path}: non-finite float is unsupported")
            return item
        if isinstance(item, (date, datetime)):
            return {
                "$yaml": "datetime" if isinstance(item, datetime) else "date",
                "value": item.isoformat(),
            }
        if not isinstance(item, (list, dict)):
            raise TypeError(f"{path}: unsupported YAML type {type(item).__name__}")
        identity = id(item)
        if identity in active:
            raise ValueError(f"{path}: recursive YAML alias is unsupported")
        active.add(identity)
        try:
            if isinstance(item, list):
                return [
                    visit(child, path=f"{path}[{index}]", depth=depth + 1)
                    for index, child in enumerate(item)
                ]
            if all(isinstance(key, str) for key in item) and "$yaml" not in item:
                return {
                    key: visit(child, path=f"{path}[{key!r}]", depth=depth + 1)
                    for key, child in item.items()
                }
            pairs = [
                [
                    visit(key, path=f"{path}.key", depth=depth + 1),
                    visit(child, path=f"{path}[{key!r}]", depth=depth + 1),
                ]
                for key, child in item.items()
            ]
            pairs.sort(key=lambda pair: json.dumps(pair[0], sort_keys=True))
            return {"$yaml": "mapping", "items": pairs}
        finally:
            active.remove(identity)

    return visit(value, path="$", depth=0)
