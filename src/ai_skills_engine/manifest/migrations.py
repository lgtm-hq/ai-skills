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
        if source in visited:
            raise ValueError(f"Cyclic identity migration at {selector}")
        visited.add(source)
        selector = migrations[source] + selector[len(source) :]
