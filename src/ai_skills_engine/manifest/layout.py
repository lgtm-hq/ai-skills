"""Opaque byte layout snapshots, independent of manifest semantic values."""

from textwrap import wrap
from typing import Any


def encode_template(raw: bytes) -> dict[str, list[str]]:
    """Encode original bytes as short scalars without linting embedded YAML.

    Args:
        raw: Original UTF-8 legacy registry bytes, including comments/newlines.

    Returns:
        JSON-compatible layout extension with deterministic hexadecimal chunks.
    """
    return {"hex": wrap(raw.hex(), width=64)}


def decode_template(value: Any) -> str:
    """Decode a byte layout snapshot, accepting literal author templates too.

    Args:
        value: Encoded snapshot or a literal YAML template string.

    Returns:
        Original UTF-8 text without normalizing newlines or spacing.

    Raises:
        ValueError: If the extension is malformed or not valid UTF-8/hexadecimal.
    """
    if isinstance(value, str):
        return value
    if (
        not isinstance(value, dict)
        or set(value) != {"hex"}
        or not isinstance(value["hex"], list)
        or not all(isinstance(part, str) for part in value["hex"])
    ):
        raise ValueError("Invalid x-legacy-format byte template")
    return bytes.fromhex("".join(value["hex"])).decode("utf-8")
