"""Read and validate packaged host rules without author-checkout fallbacks."""

import json
from functools import cache

# nosemgrep: python37-compatibility-importlib2 - runtime requires Python >=3.13
from importlib import resources
from typing import Any

from ai_skills_engine.inventory.host_attribute import HostAttribute, valid_rule
from ai_skills_engine.inventory.yaml_value import normalize_yaml_value
from ai_skills_engine.manifest.diagnostic import Diagnostic
from ai_skills_engine.registry.registry import load_unique_yaml_text

_PORTABLE = frozenset({"name", "description", "license", "compatibility", "metadata"})
_HOSTS = frozenset({"claude-code", "codex", "cursor"})


def load_host_attributes(text: str | None = None) -> dict[str, dict[str, Any]]:
    """Validate host-attribute declarations before any rule is used.

    Args:
        text: Optional explicit data, useful for offline rule validation.

    Returns:
        Validated rule definitions.

    Raises:
        ValueError: On missing hosts, semantics, forbidden drops or unknown rules.
        TypeError: If definitions are not mappings.
    """
    if text is None:
        text = (
            resources.files("ai_skills_engine.data")
            .joinpath("host_attributes.yaml")
            .read_text(encoding="utf-8")
        )
    data = load_unique_yaml_text(text=text, source="host_attributes.yaml")
    if not isinstance(data, dict):
        raise TypeError("Host attributes must be a mapping")
    for key, definition in data.items():
        if not isinstance(key, str) or not isinstance(definition, dict):
            raise TypeError("Invalid host attribute definition")
        semantics, hosts = definition.get("semantics"), definition.get("hosts")
        if (
            not isinstance(semantics, str)
            or not semantics
            or not isinstance(hosts, dict)
            or not _HOSTS.issubset(hosts)
        ):
            raise ValueError(
                f"{key}: semantics and explicit per-host rules are required"
            )
        for host, rule in hosts.items():
            if not isinstance(host, str) or not valid_rule(rule):
                raise ValueError(
                    f"{key}: invalid rule {rule!r}; drop is forbidden, "
                    "including invocation/activation/permission semantics"
                )
    return data


@cache
def _packaged_host_attributes() -> dict[str, dict[str, Any]]:
    """Validate the immutable packaged rule table once per process.

    A failed validation is not cached, so every caller still observes it.

    Returns:
        Validated packaged rule definitions (read-only by convention).
    """
    return load_host_attributes()


def inspect_attributes(
    *,
    metadata: dict[str, Any],
    location: str,
) -> tuple[tuple[HostAttribute, ...], tuple[Diagnostic, ...]]:
    """Retain host-specific values and report unknown fields as lint.

    Args:
        metadata: Source frontmatter, never used for dependency edges.
        location: Stable capability identity for diagnostics.

    Returns:
        Immutable attribute records and warning diagnostics.
    """
    definitions = _packaged_host_attributes()
    attributes: list[HostAttribute] = []
    diagnostics: list[Diagnostic] = []
    for key, value in sorted(metadata.items()):
        definition = definitions.get(key)
        if definition is None:
            if key in _PORTABLE:
                continue
            diagnostics.append(
                Diagnostic(
                    "inventory.unknown-frontmatter",
                    location,
                    f"Unknown frontmatter key: {key}",
                    warning=True,
                )
            )
            definition = {
                "semantics": "unknown",
                "hosts": dict.fromkeys(_HOSTS, "unverified"),
            }
        try:
            value_json = json.dumps(
                normalize_yaml_value(value), sort_keys=True, allow_nan=False
            )
        except (TypeError, ValueError) as error:
            diagnostics.append(
                Diagnostic(
                    "inventory.invalid-host-attribute",
                    location,
                    f"{key}: {error}; correct the attribute value before use; "
                    "host semantics remain unverified",
                )
            )
            continue
        attribute = HostAttribute(
            key=key,
            value_json=value_json,
            semantics=definition["semantics"],
            hosts=tuple(sorted(definition["hosts"].items())),
        )
        attributes.append(attribute)
        rules = ", ".join(f"{host}={rule}" for host, rule in attribute.hosts)
        diagnostics.append(
            Diagnostic(
                "inventory.host-specific-frontmatter",
                location,
                f"{key} ({attribute.semantics}): {rules}; strict unverified=refuse",
                warning=True,
            )
        )
    return tuple(attributes), tuple(diagnostics)
