"""Role-specific declarative shape checks; source bytes are never executed."""

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from ai_skills_engine.frontmatter import read_frontmatter_name, split_frontmatter
from ai_skills_engine.manifest.identity import Role
from ai_skills_engine.registry.registry import load_unique_yaml_text


class Dialect(StrEnum):
    """Source syntaxes, deliberately separate from semantic roles."""

    AGENT_SKILLS = "agent-skills"
    CLAUDE_CODE_AGENT = "claude-code-agent"
    MARKDOWN_INSTRUCTION = "markdown-instruction"
    CURSOR_RULE = "cursor-rule"
    CLAUDE_CODE_COMMAND = "claude-code-command"
    CLAUDE_CODE_HOOKS = "claude-code-hooks"
    MCP = "mcp"


def _json_object(path: Path) -> dict[str, Any]:
    """Read a duplicate-key-safe JSON object, with no executable evaluation.

    Args:
        path: Configuration file.

    Returns:
        Parsed object.

    Raises:
        ValueError: On invalid JSON or duplicate keys.
        TypeError: If the JSON root is not an object.
    """

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        """Reject ambiguous JSON keys."""
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    if not isinstance(data, dict):
        raise TypeError("Configuration must be a JSON object")
    return data


def _hooks_shape(data: dict[str, Any]) -> bool:
    """Check actual event registrations, not literal command mentions.

    Args:
        data: Parsed configuration.

    Returns:
        Whether the configuration declares events and nonempty command hooks.
    """
    events = data.get("hooks")
    if not isinstance(events, dict) or not events:
        return False
    for event, registrations in events.items():
        if (
            not isinstance(event, str)
            or not event
            or not isinstance(registrations, list)
            or not registrations
        ):
            return False
        for registration in registrations:
            if not isinstance(registration, dict):
                return False
            hooks = registration.get("hooks")
            if not isinstance(hooks, list) or not hooks:
                return False
            if not all(
                isinstance(hook, dict)
                and hook.get("type") == "command"
                and isinstance(hook.get("command"), str)
                and bool(hook["command"].strip())
                for hook in hooks
            ):
                return False
    return True


def _integration_shape(data: dict[str, Any]) -> bool:
    """Check declared MCP commands/endpoints without invoking either.

    Args:
        data: Parsed configuration.

    Returns:
        Whether all named servers declare a command or endpoint.
    """
    servers = data.get("mcpServers")
    return (
        isinstance(servers, dict)
        and bool(servers)
        and all(
            isinstance(name, str)
            and bool(name)
            and isinstance(server, dict)
            and any(
                isinstance(server.get(key), str) and bool(server[key].strip())
                for key in ("command", "url")
            )
            for name, server in servers.items()
        )
    )


def inspect_role(*, source: Path, role: Role) -> tuple[Dialect, dict[str, Any]]:
    """Recognize supported shapes only for the explicitly declared role.

    Args:
        source: Safe capability path.
        role: Manifest role, or legacy skill/agent role.

    Returns:
        Source dialect and parsed Markdown frontmatter.

    Raises:
        ValueError: On missing entrypoint, invalid frontmatter or role mismatch.
    """
    if role == Role.SKILL:
        if (
            not source.is_dir()
            or not (source / "SKILL.md").is_file()
            or (source / "SKILL.md").is_symlink()
        ):
            raise ValueError("skill requires a directory containing a regular SKILL.md")
        entry = source / "SKILL.md"
        read_frontmatter_name(text=entry.read_text(encoding="utf-8"))
        dialect = Dialect.AGENT_SKILLS
    elif role in {Role.SPECIALIST, Role.INSTRUCTION, Role.WORKFLOW}:
        if not source.is_file() or source.suffix.lower() not in {".md", ".mdc"}:
            raise ValueError(f"{role} requires a Markdown file")
        if source.suffix.lower() == ".mdc" and role != Role.INSTRUCTION:
            raise ValueError(".mdc is an instruction dialect")
        entry = source
        dialect = {
            Role.SPECIALIST: Dialect.CLAUDE_CODE_AGENT,
            Role.INSTRUCTION: (
                Dialect.CURSOR_RULE
                if source.suffix.lower() == ".mdc"
                else Dialect.MARKDOWN_INSTRUCTION
            ),
            Role.WORKFLOW: Dialect.CLAUDE_CODE_COMMAND,
        }[role]
    else:
        if not source.is_file() or source.suffix.lower() != ".json":
            raise ValueError(f"{role} requires a declarative JSON file")
        data = _json_object(source)
        check = _hooks_shape if role == Role.LIFECYCLE else _integration_shape
        if not check(data):
            raise ValueError(f"Invalid {role} configuration shape")
        return (
            Dialect.CLAUDE_CODE_HOOKS if role == Role.LIFECYCLE else Dialect.MCP
        ), {}
    frontmatter, body = split_frontmatter(entry.read_text(encoding="utf-8"))
    if frontmatter is None:
        if role == Role.INSTRUCTION and body.strip():
            return dialect, {}
        raise ValueError(f"{role} requires YAML frontmatter")
    metadata = load_unique_yaml_text(text=frontmatter, source=entry.name)
    if not isinstance(metadata, dict) or not all(
        isinstance(key, str) for key in metadata
    ):
        raise ValueError("Frontmatter must be a string-keyed mapping")
    if role != Role.INSTRUCTION and (
        not isinstance(metadata.get("description"), str)
        or not metadata["description"].strip()
    ):
        raise ValueError("Frontmatter requires a nonempty description")
    return dialect, metadata


def destination_names(
    *, source: Path, role: Role, metadata: dict[str, Any]
) -> tuple[str, ...]:
    """Observe declared destination names/keys without projecting or executing.

    Args:
        source: Validated payload entrypoint.
        role: Declared semantic role.
        metadata: Already parsed Markdown frontmatter.

    Returns:
        Source names or configuration keys, independent of stable identity.
    """
    if role in {Role.LIFECYCLE, Role.INTEGRATION}:
        field = "hooks" if role == Role.LIFECYCLE else "mcpServers"
        return tuple(sorted(_json_object(source)[field]))
    name = metadata.get("name")
    return (
        (
            name
            if isinstance(name, str) and name
            else source.name if source.is_dir() else source.stem
        ),
    )
