"""Advisory semantic-version changes over resolved artifact indexes."""

import re
from collections.abc import Mapping
from typing import Any

from ai_skills_engine.semver_advice_result import SemverAdvice

# Only a tool name and an optional single, quoted-string-aware argument group.
# Unsupported syntax stays uncertain; commands and patterns are never evaluated.
_TOOL_EXPRESSION = (
    r"[A-Za-z_][A-Za-z0-9_.*-]*"
    r"""(?:\((?:[^()'"\\]|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')*\))?"""
)


def _capabilities(index: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten package inventories without resolving any dependency edges.

    Args:
        index: Before/after resolved artifact index.

    Returns:
        Capabilities keyed by stable qualified ID.
    """
    return {
        item["id"]: item
        for package in index.get("packages", ())
        for item in package["capabilities"]
    }


def _activation_values(value: Any) -> set[str] | None:
    """Compare activation patterns independently of tool permission syntax.

    Args:
        value: JSON scalar or array.

    Returns:
        Whole patterns for literal comparison, or None for unsupported syntax.
        Only arrays declare unambiguous list boundaries; scalar patterns are
        never split on commas or whitespace and no pattern is executed.
    """
    if value is None:
        return set()
    if isinstance(value, list):
        return set(value) if all(isinstance(item, str) for item in value) else None
    if isinstance(value, str):
        return {value} if value else set()
    return None


def _permission_values(value: Any) -> set[str] | None:
    """Retain complete literal permissions, or signal unsupported syntax.

    Args:
        value: Absent declaration, tool-list string or array of expressions.

    Returns:
        Complete expressions, preserving their argument bytes; None if uncertain.
    """
    if value is None:
        return set()
    if isinstance(value, list):
        if any(
            not isinstance(item, str)
            or re.fullmatch(_TOOL_EXPRESSION, item.strip()) is None
            for item in value
        ):
            return None
        return {item.strip() for item in value}
    if (
        not isinstance(value, str)
        or re.fullmatch(
            rf"\s*(?:{_TOOL_EXPRESSION}(?:[\s,]+{_TOOL_EXPRESSION})*)?\s*", value
        )
        is None
    ):
        return None
    return {match.group() for match in re.finditer(_TOOL_EXPRESSION, value)}


def _widened(*, before: dict[str, Any], after: dict[str, Any]) -> tuple[str, ...]:
    """Detect known widening and conservatively flag changed unknown semantics.

    Args:
        before: Previous capability record.
        after: Current capability record.

    Returns:
        Names of widened activation, invocation or permission fields.
    """
    old = {item["key"]: item for item in before.get("hostAttributes", ())}
    new = {item["key"]: item for item in after.get("hostAttributes", ())}
    widened = set()
    for key in old.keys() | new.keys():
        previous, current = old.get(key, {}), new.get(key, {})
        left, right = previous.get("value"), current.get("value")
        if left == right:
            continue
        if key == "disable-model-invocation":
            broadens = left is True and right is not True
        elif key == "user-invocable":
            broadens = left is False and right is not False
        elif key == "alwaysApply":
            broadens = right is True and left is not True
        elif key in {"paths", "globs"}:
            left_patterns = _activation_values(left)
            right_patterns = _activation_values(right)
            if left_patterns is None or right_patterns is None:
                broadens = True
            else:
                broadens = bool(left) and (
                    not right_patterns or not right_patterns.issubset(left_patterns)
                )
        elif key in {"allowed-tools", "tools", "disallowedTools"}:
            left_permissions = _permission_values(left)
            right_permissions = _permission_values(right)
            if left_permissions is None or right_permissions is None:
                broadens = True
            elif key == "disallowedTools":
                broadens = not left_permissions.issubset(right_permissions)
            elif left is not None and not left_permissions:
                # An explicit empty allowlist grants nothing; absence grants all.
                broadens = right is None or bool(right_permissions)
            else:
                broadens = bool(left) and (
                    not right_permissions
                    or not right_permissions.issubset(left_permissions)
                )
        else:
            broadens = previous.get("semantics", current.get("semantics")) in {
                "activation",
                "permission",
                "invocation-restriction",
            }
        if broadens:
            widened.add(key)
    return tuple(sorted(widened))


def recommend_semver(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> SemverAdvice:
    """Recommend, never enforce, the highest change level with stable reasons.

    Unknown activation/permission changes are conservatively major: static
    comparison cannot prove arbitrary glob or permission-mode containment.

    Args:
        before: Previous resolved artifact index.
        after: Current resolved artifact index.

    Returns:
        Major for removals, broken requires or widening; minor for additions;
        patch for changed content/metadata; none for equal capability inventories.
    """
    old, new = _capabilities(before), _capabilities(after)
    major = [f"Capability removed: {key}" for key in sorted(old.keys() - new.keys())]
    for key, item in sorted(new.items()):
        major.extend(
            f"Broken requires: {key} -> {target}"
            for target in item["requires"]
            if target not in new
        )
        if key in old:
            major.extend(
                f"Widened {field}: {key}"
                for field in _widened(before=old[key], after=item)
            )
            if old[key].get("executionSurface", {}) != item.get("executionSurface", {}):
                major.append(f"Execution surface changed: {key}")
    minor = [f"Capability added: {key}" for key in sorted(new.keys() - old.keys())]
    patch = [
        f"Content or metadata changed: {key}"
        for key in sorted(old.keys() & new.keys())
        if old[key] != new[key]
    ]
    if before.get("legalFiles", []) != after.get("legalFiles", []):
        patch.append("License or notice content changed")
    if major:
        return SemverAdvice(
            level="major", reasons=tuple(sorted(set(major + minor + patch)))
        )
    if minor:
        return SemverAdvice(level="minor", reasons=tuple(sorted(minor + patch)))
    if patch:
        return SemverAdvice(level="patch", reasons=tuple(sorted(patch)))
    return SemverAdvice(level="none", reasons=())
