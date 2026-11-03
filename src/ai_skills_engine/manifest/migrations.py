"""Explicit identity migration resolution shared by inventory and selection."""

from collections.abc import Mapping


def migrate(selector: str, migrations: Mapping[str, str]) -> str:
    """Follow only declared identity migrations, including package migrations.

    Args:
        selector: Original qualified selector.
        migrations: Explicit old to new identities.

    Returns:
        Current selector, without inferring any relationship from names/hashes.

    Raises:
        ValueError: On a cyclic migration.
    """
    visited: set[str] = set()
    # Prefix rewrites preserve the suffix. A growing suffix under a repeated
    # rule can never reach an exact identity; guard it as well as state cycles.
    suffixes: dict[str, set[str]] = {}
    while True:
        source = next(
            (
                old
                for old in sorted(migrations, key=lambda item: (-len(item), item))
                if selector == old or selector.startswith(old + ":")
            ),
            None,
        )
        if source is None:
            return selector
        suffix = selector[len(source) :]
        if selector in visited or any(
            suffix != previous and suffix.endswith(previous)
            for previous in suffixes.get(source, set())
        ):
            raise ValueError(f"Cyclic identity migration at {selector}")
        visited.add(selector)
        suffixes.setdefault(source, set()).add(suffix)
        selector = migrations[source] + selector[len(source) :]
