#!/usr/bin/env python3
"""Parse the spike Python pin with the runner's bootstrap interpreter."""

import json
from pathlib import Path


def python_pin(path: Path) -> str:
    """Read a nonempty version string, independent of JSON layout or newlines.

    Args:
        path: Spike settings JSON.

    Returns:
        Python runtime version.

    Raises:
        ValueError: If the Python pin is invalid.
    """
    value = json.loads(path.read_text(encoding="utf-8"))["python"]
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise ValueError("invalid Python pin")
    return value


if __name__ == "__main__":
    print(f"python={python_pin(Path(__file__).resolve().parents[1] / 'settings.json')}")
