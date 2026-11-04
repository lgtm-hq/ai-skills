"""Advisory bake diff rules over resolved capability metadata."""

from copy import deepcopy
from typing import Any

import pytest
from assertpy import assert_that

from ai_skills_engine.semver_advice import recommend_semver


@pytest.fixture
def before_index() -> dict[str, Any]:
    """Provide a compact resolved diff input, without source acquisition.

    Returns:
        Two capabilities with one declared hard dependency.
    """
    return {
        "packages": [
            {
                "id": "fixture/tools",
                "capabilities": [
                    {
                        "id": "fixture/tools:skill/start",
                        "requires": ["fixture/tools:skill/peer"],
                        "treeDigest": "same",
                        "hostAttributes": [],
                    },
                    {
                        "id": "fixture/tools:skill/peer",
                        "requires": [],
                        "treeDigest": "same",
                        "hostAttributes": [],
                    },
                ],
            }
        ]
    }


@pytest.mark.parametrize(
    ("change", "level"),
    [
        ("same", "none"),
        ("content", "patch"),
        ("add", "minor"),
        ("remove", "major"),
        ("rename", "major"),
        ("broken", "major"),
    ],
)
def test_advisory_diff_rules(
    before_index: dict[str, Any], change: str, level: str
) -> None:
    """Advice prioritizes broken/removal changes over additions and content."""
    after = deepcopy(before_index)
    caps = after["packages"][0]["capabilities"]
    if change == "content":
        caps[0]["treeDigest"] = "changed"
    elif change == "add":
        caps.append(
            {"id": "fixture/tools:skill/added", "requires": [], "hostAttributes": []}
        )
    elif change == "remove":
        caps.pop(0)
    elif change == "rename":
        caps[0]["id"] = "fixture/tools:skill/new-id"
    elif change == "broken":
        caps[0]["requires"].append("fixture/tools:skill/absent")
    result = recommend_semver(before_index, after)
    assert_that(result.level).is_equal_to(level)
    assert_that(result.reasons).is_sorted()
    assert_that(bool(result.reasons)).is_equal_to(level != "none")


@pytest.mark.parametrize(
    ("key", "semantics", "old", "new", "level"),
    [
        ("disable-model-invocation", "invocation-restriction", True, None, "major"),
        ("disable-model-invocation", "invocation-restriction", True, False, "major"),
        ("disable-model-invocation", "invocation-restriction", False, True, "patch"),
        ("user-invocable", "invocation-restriction", False, True, "major"),
        ("allowed-tools", "permission", ["Read"], ["Read", "Write"], "major"),
        ("allowed-tools", "permission", ["Read"], None, "major"),
        ("allowed-tools", "permission", ["Read", "Write"], ["Read"], "patch"),
        ("disallowedTools", "permission", ["Write"], [], "major"),
        ("tools", "permission", "Read", "Read, Write", "major"),
        ("paths", "activation", ["src/**"], ["**"], "major"),
        ("globs", "activation", ["src/**"], None, "major"),
        ("globs", "activation", ["src/**", "tests/**"], ["src/**"], "patch"),
        ("alwaysApply", "activation", False, True, "major"),
        ("permissionMode", "permission", "default", "bypassPermissions", "major"),
        ("model", "model-selection", "small", "large", "patch"),
    ],
)
def test_activation_and_permission_changes(
    before_index: dict[str, Any],
    key: str,
    semantics: str,
    old: object,
    new: object,
    level: str,
) -> None:
    """Widening declarations are major; literal narrowing stays advisory patch."""
    before_index["packages"][0]["capabilities"][0]["hostAttributes"] = [
        {"key": key, "semantics": semantics, "value": old}
    ]
    after = deepcopy(before_index)
    after["packages"][0]["capabilities"][0]["hostAttributes"] = (
        [] if new is None else [{"key": key, "semantics": semantics, "value": new}]
    )
    result = recommend_semver(before_index, after)
    assert_that(result.level).is_equal_to(level)
    if level == "major":
        assert_that("\n".join(result.reasons)).contains("Widened " + key)
