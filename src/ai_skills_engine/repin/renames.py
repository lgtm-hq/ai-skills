"""Apply only explicitly declared identity migrations to consumer selectors.

A rename comes from a consumer ``overrides.migrations`` entry or a
publisher-local migration in the upstream's own manifest. Nothing is inferred
from names or content.
"""

from collections.abc import Collection, Mapping
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from ai_skills_engine.manifest.identity import matches, parse_id
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.migrations import migrate
from ai_skills_engine.repin.selector_status import SelectorStatus

type Migrations = dict[str, tuple[str, str]]


def declared_migrations(
    *, document: Mapping[str, Any], tree: Path | None, publisher: str
) -> Migrations:
    """Collect consumer and publisher-local upstream identity migrations.

    Args:
        document: Consumer manifest.
        tree: New upstream tree, which may carry its own manifest.
        publisher: Upstream publisher namespace.

    Returns:
        Old ID to ``(new ID, "consumer" | "upstream")``; consumer wins.

    Raises:
        ValueError: On a malformed upstream migration ID.
    """
    found: Migrations = {}
    upstream = tree / "ai-skills.yaml" if tree is not None else None
    if upstream is not None and upstream.is_file():
        overrides = read_document(upstream).get("overrides")
        moves = overrides.get("migrations", []) if isinstance(overrides, dict) else []
        for item in moves if isinstance(moves, list) else []:
            if not isinstance(item, dict):
                continue
            source, target = item.get("from"), item.get("to")
            if (
                isinstance(source, str)
                and isinstance(target, str)
                and source.startswith(publisher + "/")
                and target.startswith(publisher + "/")
            ):
                parse_id(source)
                parse_id(target)
                found[source] = (target, "upstream")
    overrides = document.get("overrides") or {}
    for item in overrides.get("migrations", []):
        found[item["from"]] = (item["to"], "consumer")
    return found


def _targets(migrations: Migrations) -> dict[str, str]:
    """Drop the declaring source.

    Args:
        migrations: Declared migrations.

    Returns:
        Old ID to new ID.
    """
    return {source: target for source, (target, _origin) in migrations.items()}


def rewrite_filters(
    *,
    entry: dict[str, Any],
    migrations: Migrations,
    identities: Collection[str],
) -> tuple[dict[str, Any], tuple[SelectorStatus, ...]]:
    """Rewrite include/exclude selectors naming a migrated ID and count matches.

    Args:
        entry: Consumer vendor declaration (not modified).
        migrations: Declared migrations.
        identities: Every observed capability/resource ID at the new revision.

    Returns:
        Rewritten declaration and selector outcomes (dead when unmatched).
    """
    result = deepcopy(entry)
    statuses = []
    moves = _targets(migrations)
    for field in ("include", "exclude"):
        if field not in result:
            continue
        rewritten = []
        for selector in result[field]:
            target = migrate(selector, moves, identities=identities)
            count = sum(matches(selector=target, identity=item) for item in identities)
            renamed = target != selector
            statuses.append(
                SelectorStatus(
                    location=field,
                    selector=target,
                    matches=count,
                    status="dead" if not count else "renamed" if renamed else "ok",
                    detail=f"{selector} -> {target}" if renamed else "",
                )
            )
            rewritten.append(target)
        result[field] = rewritten
    return result, tuple(statuses)


def rewrite_mapping(
    *, entry: dict[str, Any], vendor: str, migrations: Migrations
) -> tuple[dict[str, Any], tuple[SelectorStatus, ...]]:
    """Rename mapped skill selectors along declared same-package migrations.

    Mapped skill IDs derive from the skill directory name, so a declared
    ``<vendor>/<package>:skill/<old>`` to ``...:skill/<new>`` migration renames
    the listed selector together with its ``renameSkills`` and ``capabilities``
    keys. Other migrations leave the mapping untouched.

    Args:
        entry: Consumer vendor declaration (not modified).
        vendor: Consumer vendor alias (the mapped publisher namespace).
        migrations: Declared migrations.

    Returns:
        Rewritten declaration and the renamed selectors.
    """
    result = deepcopy(entry)
    statuses = []
    moves = _targets(migrations)
    for package in (result.get("mapping") or {}).get("packages") or ():
        if package["skills"] == "*":
            continue
        prefix = f"{vendor}/{package['id']}:skill/"
        renamed = []
        for name in package["skills"]:
            source = prefix + PurePosixPath(name).name
            target = moves.get(source, "")
            if not target.startswith(prefix):
                renamed.append(name)
                continue
            new_name = target[len(prefix) :]
            parent = PurePosixPath(name).parent
            selector = (
                new_name if parent == PurePosixPath(".") else f"{parent}/{new_name}"
            )
            renamed.append(selector)
            old_name = PurePosixPath(name).name
            for field in ("renameSkills", "capabilities"):
                values = package.get(field)
                if isinstance(values, dict) and old_name in values:
                    package[field] = {
                        (new_name if key == old_name else key): value
                        for key, value in values.items()
                    }
            statuses.append(
                SelectorStatus(
                    location=f"mapping.packages[{package['id']}].skills",
                    selector=selector,
                    matches=0,
                    status="renamed",
                    detail=f"{name} -> {selector} ({migrations[source][1]})",
                )
            )
        package["skills"] = renamed
    return result, tuple(statuses)
