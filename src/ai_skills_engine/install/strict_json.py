"""Strict JSON decoding shared by index and lock pin readers."""

import json
from typing import Any

from ai_skills_engine.install.errors import InstallError


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build an object while rejecting duplicate keys.

    Args:
        pairs: Decoded key/value pairs in document order.

    Returns:
        The decoded object.

    Raises:
        InstallError: If a key repeats.
    """
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InstallError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_object(data: bytes, *, source: str) -> dict[str, Any]:
    """Decode UTF-8 JSON that must be an object with unique keys.

    Args:
        data: Exact file bytes.
        source: Label used in diagnostics.

    Returns:
        Decoded object.

    Raises:
        InstallError: For invalid UTF-8, malformed JSON or a non-object root.
    """
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique)
    except InstallError as error:
        raise InstallError(f"{source}: {error}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InstallError(f"{source}: malformed JSON ({error})") from error
    if not isinstance(value, dict):
        raise InstallError(f"{source}: expected a JSON object")
    return value
