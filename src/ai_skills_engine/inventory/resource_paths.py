"""Explicit structural path declarations, independent of dependency edges."""

from collections.abc import Mapping
from pathlib import PurePosixPath


def declared_paths(extensions: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    """Read file-to-JSON-pointer declarations from x-resource-paths.

    Args:
        extensions: Manifest capability or resource extensions.

    Returns:
        Sorted immutable file/pointer pairs. These never add resource edges.

    Raises:
        ValueError: For malformed or unsafe declarations.
        TypeError: For a non-mapping declaration.
    """
    raw = extensions.get("x-resource-paths", {})
    if not isinstance(raw, Mapping):
        raise TypeError("x-resource-paths must map payload files to JSON pointers")
    result = set()
    for file, pointers in raw.items():
        if (
            not isinstance(file, str)
            or not file
            or "\\" in file
            or PurePosixPath(file).is_absolute()
            or ".." in PurePosixPath(file).parts
            or not isinstance(pointers, (tuple, list))
        ):
            raise ValueError("Invalid x-resource-paths file or pointer list")
        for pointer in pointers:
            if not isinstance(pointer, str) or not pointer.startswith("/"):
                raise ValueError("x-resource-paths requires nonempty JSON pointers")
            result.add((file, pointer))
    return tuple(sorted(result))
