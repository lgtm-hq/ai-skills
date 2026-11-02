"""Schema-validated dictionaries to frozen records and back."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import StrEnum
from types import MappingProxyType, UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from ai_skills_engine.manifest.record import Record


def field_key(name: str) -> str:
    """Translate a Python field to the schema's camelCase spelling.

    Args:
        name: Dataclass field name.

    Returns:
        Serialized key.
    """
    first, *rest = name.rstrip("_").split("_")
    return first + "".join(part.title() for part in rest)


def decode(value: Any, kind: Any) -> Any:
    """Convert an already schema-validated value to its annotated record type.

    Args:
        value: Validated JSON-compatible value.
        kind: Runtime annotation, including nested containers.

    Returns:
        Frozen record, immutable container, enum or scalar.
    """
    origin, args = get_origin(kind), get_args(kind)
    if value is None:
        return None
    if origin in {UnionType, Union}:
        chosen = next(
            item
            for item in args
            if item is not type(None)
            and (get_origin(item) is tuple) == isinstance(value, list)
        )
        return decode(value, chosen)
    if isinstance(kind, type) and is_dataclass(kind):
        hints = get_type_hints(kind)
        values = {
            field.name: decode(value[field_key(field.name)], hints[field.name])
            for field in fields(kind)
            if field.name != "extensions" and field_key(field.name) in value
        }
        values["extensions"] = MappingProxyType(
            {
                key: decode(item, object)
                for key, item in value.items()
                if key.startswith("x-")
            },
        )
        return kind(**values)
    if origin is tuple or isinstance(value, list):
        return tuple(decode(item, args[0] if args else object) for item in value)
    if origin is Mapping or isinstance(value, dict):
        return MappingProxyType(
            {
                key: decode(item, args[1] if args else object)
                for key, item in value.items()
            }
        )
    if isinstance(kind, type) and issubclass(kind, StrEnum):
        return kind(value)
    return value


def encode(value: Any) -> Any:
    """Return plain JSON-compatible containers without dropping extensions.

    Args:
        value: Frozen record or nested value.

    Returns:
        Dictionary, list or scalar suitable for YAML/JSON serialization.
    """
    if isinstance(value, Record):
        return {
            **{
                field_key(field.name): encode(item)
                for field in fields(value)
                if field.name != "extensions"
                and (item := getattr(value, field.name)) is not None
            },
            **{key: encode(item) for key, item in value.extensions.items()},
        }
    if isinstance(value, Mapping):
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [encode(item) for item in value]
    if isinstance(value, StrEnum):
        return str(value)
    return value
