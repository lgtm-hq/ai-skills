"""Resource boundary and mention lint, deliberately incapable of adding edges."""

import re
from collections.abc import Mapping
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token

from ai_skills_engine.frontmatter import split_frontmatter
from ai_skills_engine.inventory.capability import Capability
from ai_skills_engine.inventory.capability_id import CapabilityId
from ai_skills_engine.inventory.resource_id import ResourceId
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.registry.safe_tree import (
    _local_markdown_path,
    iter_markdown_destinations,
    walk_files,
)


def _prose(tokens: list[Token]) -> str:
    """Collect real prose, ignoring code fences, code spans and HTML literals.

    Args:
        tokens: Parsed CommonMark tokens.

    Returns:
        Plain prose for advisory name matching.
    """
    return " ".join(
        token.content if token.type == "text" else _prose(token.children or [])
        for token in tokens
        if token.type
        not in {"code_inline", "fence", "code_block", "html_block", "html_inline"}
    )


def _allowed(*, target: Path, source: Path, resources: tuple[Path, ...]) -> bool:
    """Check exact file/directory boundaries, not common string prefixes.

    Args:
        target: Resolved link destination.
        source: Capability source.
        resources: Explicitly referenced resource roots.

    Returns:
        Whether the target is within a payload or declared resource.
    """
    return any(
        target == root or (root.is_dir() and target.is_relative_to(root))
        for root in (source, *resources)
    )


def lint_inventory(
    *,
    capabilities: tuple[Capability, ...],
    sources: Mapping[CapabilityId, Path],
    resource_paths: Mapping[ResourceId, Path],
) -> tuple[Diagnostic, ...]:
    """Report actual Markdown destinations and undeclared prose mentions.

    Args:
        capabilities: Edge-resolved immutable records.
        sources: Physical inputs used only while collecting observations.
        resource_paths: Physical resource roots by declared identity.

    Returns:
        Error/warning observations with no implicit dependency graph changes.
    """
    diagnostics: list[Diagnostic] = []
    for capability in capabilities:
        source = sources[capability.id]
        base = source if source.is_dir() else source.parent
        resources = tuple(resource_paths[identity] for identity in capability.resources)
        markdown_files = [
            (str(item.path), base / item.path)
            for item in capability.payload
            if item.path.suffix.lower() in {".md", ".markdown", ".mdc"}
        ]
        for identity in capability.resources:
            resource = resource_paths[identity]
            files = (
                walk_files(root=resource) if resource.is_dir() else iter((resource,))
            )
            resource_base = resource if resource.is_dir() else resource.parent
            markdown_files.extend(
                (f"{identity}/{path.relative_to(resource_base).as_posix()}", path)
                for path in files
                if path.suffix.lower() in {".md", ".markdown", ".mdc"}
            )
        texts = []
        for label, path in sorted(markdown_files):
            try:
                text = split_frontmatter(path.read_text(encoding="utf-8"))[1]
            except (OSError, UnicodeError) as error:
                diagnostics.append(
                    Diagnostic(
                        "inventory.invalid-payload",
                        str(capability.id),
                        f"{label}: unreadable Markdown: {type(error).__name__}",
                    )
                )
                continue
            texts.append(text)
            for raw in sorted(set(iter_markdown_destinations(text=text))):
                try:
                    local = _local_markdown_path(raw_target=raw)
                    if local is None:
                        continue
                    target = path.parent / local
                    resolved = target.resolve()
                    if (
                        not _allowed(
                            target=resolved, source=source, resources=resources
                        )
                        or not resolved.exists()
                    ):
                        raise ValueError(
                            "outside payload/declared resources or missing"
                        )
                    # Reject symlink traversal even if it resolves back inside.
                    for ancestor in (target, *target.parents):
                        if ancestor.is_symlink():
                            raise ValueError("symlink in resource reference")
                        if ancestor == base:
                            break
                except ValueError as error:
                    diagnostics.append(
                        Diagnostic(
                            "inventory.undeclared-resource",
                            str(capability.id),
                            f"{label}: {raw}: {error}",
                        )
                    )
        prose = _prose(MarkdownIt("commonmark").parse("\n".join(texts)))
        declared = set(capability.requires + capability.related + (capability.id,))
        for other in capabilities:
            if other.id in declared or other.id.name == capability.id.name:
                continue
            names = (other.id.name, *other.aliases)
            if any(
                re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", prose)
                for name in names
            ):
                diagnostics.append(
                    Diagnostic(
                        "inventory.undeclared-mention",
                        str(capability.id),
                        f"Mention of {other.id} without requires/related",
                        warning=True,
                    )
                )
    return tuple(diagnostics)
