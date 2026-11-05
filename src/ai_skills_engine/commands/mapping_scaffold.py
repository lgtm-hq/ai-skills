"""Consumer-owned mapping scaffolds for vendors that publish no manifest.

``add`` writes a reviewed-by-nobody mapping with :data:`SCAFFOLD_MARKER` set.
Identities in a mapping are asserted by the consumer, never by the upstream,
so ``lock`` and ``validate`` refuse the scaffold until ``add --accept-mapping``
removes the marker.
"""

import os
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from ai_skills_engine.manifest.identity import SEGMENT

SCAFFOLD_MARKER = "x-mapping-scaffold"
ACCEPT_HINT = (
    "review the consumer-owned mapping, then run "
    "`ai-skills-engine add OWNER/REPO --accept-mapping`"
)
_PRUNED = frozenset({"node_modules", "__pycache__"})


def unaccepted_mappings(document: Mapping[str, Any]) -> tuple[str, ...]:
    """List vendor aliases whose mapping scaffold has not been accepted.

    Args:
        document: Parsed consumer manifest.

    Returns:
        Aliases in declaration order.
    """
    vendors = document.get("vendors", [])
    if not isinstance(vendors, list):
        return ()
    return tuple(
        str(vendor.get("id"))
        for vendor in vendors
        if isinstance(vendor, dict) and vendor.get(SCAFFOLD_MARKER) is True
    )


def require_accepted(document: Mapping[str, Any]) -> None:
    """Refuse to lock identities nobody has confirmed.

    Args:
        document: Parsed consumer manifest.

    Raises:
        ValueError: If any vendor mapping is still an unaccepted scaffold.
    """
    pending = unaccepted_mappings(document)
    if pending:
        raise ValueError(
            "consumer-asserted mapping scaffold not accepted for vendor(s) "
            f"{', '.join(pending)}; {ACCEPT_HINT}"
        )


def kebab(value: str) -> str:
    """Normalize a repository or plugin name to an identity segment.

    Args:
        value: Free-form name.

    Returns:
        Lowercase kebab-case segment, possibly empty.
    """
    characters = [
        character if character.isascii() and character.isalnum() else "-"
        for character in value.lower()
    ]
    return "-".join(part for part in "".join(characters).split("-") if part)


def discover_payloads(root: Path) -> tuple[dict[str, list[str]], list[str]]:
    """Find ``.../skills/<name>/SKILL.md`` skills and top-level ``agents/*.md``.

    Only path names are inspected: no file content is read or executed, symbolic
    links are never followed, and hidden or dependency directories are pruned.

    Args:
        root: Repository tree.

    Returns:
        Skill names keyed by their POSIX skills root, and top-level agent names.
    """
    skills: dict[str, list[str]] = {}
    for directory, children, files in os.walk(root):
        children[:] = sorted(
            name
            for name in children
            if not name.startswith(".") and name not in _PRUNED
        )
        relative = PurePosixPath(Path(directory).relative_to(root).as_posix())
        if (
            "SKILL.md" in files
            and len(relative.parts) >= 2
            and relative.parts[-2] == "skills"
            and not (Path(directory) / "SKILL.md").is_symlink()
        ):
            skills.setdefault(relative.parent.as_posix(), []).append(relative.name)
    agents_root = root / "agents"
    agents = (
        sorted(
            path.stem
            for path in agents_root.glob("*.md")
            if path.is_file()
            and not path.is_symlink()
            and re.fullmatch(SEGMENT, path.stem)
        )
        if agents_root.is_dir() and not agents_root.is_symlink()
        else []
    )
    return {key: sorted(names) for key, names in sorted(skills.items())}, agents


def mapping_scaffold(*, alias: str, root: Path) -> dict[str, Any]:
    """Propose consumer-owned mapped packages for a manifestless tree.

    Args:
        alias: Consumer vendor alias that qualifies every mapped identity.
        root: Fetched vendor tree.

    Returns:
        Schema-shaped ``mapping`` declaration.

    Raises:
        ValueError: If the tree has no ``skills/*/SKILL.md`` skills.
    """
    skills, agents = discover_payloads(root)
    if not skills:
        raise ValueError(
            "no skills/*/SKILL.md found; write the consumer mapping by hand"
        )
    packages: list[dict[str, Any]] = []
    for skills_root in skills:
        parent = PurePosixPath(skills_root).parent.as_posix()
        suffix = "skills" if parent == "." else kebab(parent) + "-skills"
        package: dict[str, Any] = {
            "id": f"{alias}-{suffix}",
            "description": f"Consumer-asserted mapping of {skills_root}.",
            "skillsRoot": skills_root,
            "skills": "*",
        }
        if not packages and agents:
            package["agents"] = agents
        packages.append(package)
    return {"skillRoots": list(skills), "packages": packages}
