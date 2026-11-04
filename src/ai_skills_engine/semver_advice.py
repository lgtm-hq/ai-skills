"""Advisory semantic-version changes over resolved artifact indexes."""

from collections.abc import Mapping
from typing import Any

from ai_skills_engine.semver_advice_result import SemverAdvice


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


def _values(value: Any) -> set[str]:
    """Compare declarative tool lists and activation patterns conservatively.

    Args:
        value: JSON scalar or array.

    Returns:
        String elements for literal set comparison; patterns are never executed.
    """
    if isinstance(value, list):
        return set(map(str, value))
    if isinstance(value, str):
        return {
            part.strip() for part in value.replace(",", " ").split() if part.strip()
        }
    return set()


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
        elif key in {"paths", "globs"} or key in {"allowed-tools", "tools"}:
            broadens = bool(left) and (
                not right or not _values(right).issubset(_values(left))
            )
        elif key == "disallowedTools":
            broadens = not _values(left).issubset(_values(right))
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
