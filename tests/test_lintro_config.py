"""Guard the default-on lintro policy without invoking tools or the network."""

from pathlib import Path

import pytest
import yaml
from assertpy import assert_that
from lintro.config.config_loader import load_config
from lintro.config.tool_config import LintroToolConfig
from pydantic import ValidationError
from yaml.nodes import MappingNode, Node, ScalarNode


def _yaml_comments(source: str) -> dict[int, str]:
    """Locate nonempty comments outside YAML tokens, including quoted strings.

    Args:
        source: YAML configuration text.

    Returns:
        Comment text keyed by its zero-based source line.
    """
    lines = source.splitlines()
    ends = [0] * len(lines)
    for token in yaml.scan(source):
        if token.start_mark.index == token.end_mark.index:
            continue
        for line in range(
            token.start_mark.line, min(token.end_mark.line + 1, len(lines))
        ):
            column = (
                token.end_mark.column
                if line == token.end_mark.line
                else len(lines[line])
            )
            ends[line] = max(ends[line], column)
    return {
        number: tail[1:].strip()
        for number, line in enumerate(lines)
        if (tail := line[ends[number] :].strip()).startswith("#") and tail[1:].strip()
    }


def _has_local_reason(
    lines: list[str],
    comments: dict[int, str],
    tool: ScalarNode,
    settings: Node,
    other_tool_lines: set[int],
) -> bool:
    """Accept a reason only within the disabled tool's own source block.

    Inherited disables require a local reason on the tool declaration or merge,
    even if the anchor itself has a comment. Aliases cannot borrow reasons from
    their definition. Flow-style sibling tools cannot share one comment.

    Args:
        lines: Configuration source lines.
        comments: Nonempty YAML comments by source line.
        tool: The local tool key node.
        settings: The tool's unresolved settings node.
        other_tool_lines: Lines declaring sibling tools, outside this reason's scope.

    Returns:
        Whether the local declaration documents the effective disable.
    """
    tool_line = tool.start_mark.line
    tool_column = tool.start_mark.column
    comments = {
        line: reason
        for line, reason in comments.items()
        if line not in other_tool_lines
    }
    if lines[tool_line][:tool_column].strip():
        return False
    if tool_line in comments:
        return True
    if not isinstance(settings, MappingNode):
        return False
    local_settings = {
        key.value: key
        for key, _ in settings.value
        if isinstance(key, ScalarNode)
        and key.start_mark.line > tool_line
        and key.start_mark.column > tool_column
    }
    setting = local_settings.get("enabled", local_settings.get("<<"))
    if setting is None:
        return False
    line = setting.start_mark.line
    previous = lines[line - 1]
    return line in comments or (
        line - 1 > tool_line
        and line - 1 in comments
        and previous.strip().startswith("#")
        and len(previous) - len(previous.lstrip()) == setting.start_mark.column
    )


@pytest.fixture
def lintro_source() -> str:
    """Return the repository's lintro configuration, including reason comments.

    Returns:
        The configuration source text.
    """
    config_path = Path(__file__).resolve().parents[1] / ".lintro-config.yaml"
    return config_path.read_text(encoding="utf-8")


def _policy_violations(source: str) -> list[str]:
    """Find allowlists and tool disables lacking a reason comment.

    Args:
        source: YAML configuration text.

    Returns:
        Policy violations with the affected setting or tool name.
    """
    try:
        config = yaml.safe_load(source)
        document = yaml.compose(source)
        comments = _yaml_comments(source)
    except (yaml.YAMLError, RecursionError):
        return ["invalid YAML configuration"]
    if not isinstance(config, dict) or not isinstance(document, MappingNode):
        return ["configuration must be a mapping"]
    violations = []
    execution = config.get("execution", {})
    if not isinstance(execution, dict):
        violations.append("execution must be a mapping")
    elif "enabled_tools" in execution:
        violations.append("execution.enabled_tools must be absent")

    tools = config.get("tools", {})
    if not isinstance(tools, dict):
        return [*violations, "tools must be a mapping"]
    # Lintro normalizes before parsing: the last spelling owns the whole entry.
    # Keep nonstring names so malformed configuration still fails closed.
    tools = {
        (name.lower() if isinstance(name, str) else name): settings
        for name, settings in tools.items()
    }
    raw_sections = {
        key.value: value for key, value in document.value if isinstance(key, ScalarNode)
    }
    raw_tools = raw_sections.get("tools")
    tool_nodes = (
        {
            key.value.lower(): (key, value)
            for key, value in raw_tools.value
            if isinstance(key, ScalarNode)
        }
        if isinstance(raw_tools, MappingNode)
        else {}
    )
    lines = source.splitlines()
    for name, settings in tools.items():
        if not isinstance(name, str):
            violations.append("tool name must be a string")
            continue
        if not isinstance(settings, (dict, bool)):
            violations.append(
                f"{name}: tool configuration must be a mapping or boolean"
            )
            continue
        try:
            # Use Lintro's boolean coercion and default, rather than duplicating them.
            tool_config = LintroToolConfig.model_validate(
                {"enabled": settings} if isinstance(settings, bool) else settings,
            )
        except ValidationError:
            violations.append(f"{name}: invalid tool configuration")
            continue
        if tool_config.enabled:
            continue
        local = tool_nodes.get(name)
        if local is None or not _has_local_reason(
            lines=lines,
            comments=comments,
            tool=local[0],
            settings=local[1],
            other_tool_lines=(
                {
                    key.start_mark.line
                    for key, _ in raw_tools.value
                    if key is not local[0]
                }
                if isinstance(raw_tools, MappingNode)
                else set()
            ),
        ):
            violations.append(f"{name}: disabled without a reason")
    return violations


def test_repository_lintro_policy(lintro_source: str) -> None:
    """Keep every future tool enabled and require documented exceptions."""
    assert_that(_policy_violations(lintro_source)).is_empty()


@pytest.mark.parametrize(
    ("settings", "enabled", "expected"),
    [
        ("  Ruff: false\n  ruff: true\n", True, []),
        ("  ruff: false\n  RUFF: {}\n", True, []),
        (
            "  ruff: true\n  Ruff: false\n",
            False,
            ["ruff: disabled without a reason"],
        ),
        ("  ruff: true\n  Ruff: false # Cost gate.\n", False, []),
        (
            "  Ruff: false # Old reason.\n  ruff: false\n",
            False,
            ["ruff: disabled without a reason"],
        ),
        (
            "  Ruff: {enabled: false}\n  ruff: {enabled: true}\n",
            True,
            [],
        ),
    ],
    ids=[
        "later-enable",
        "later-default",
        "later-disable",
        "local-reason",
        "shadowed-reason",
        "mapping-override",
    ],
)
def test_policy_matches_loader_tool_key_normalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings: str,
    enabled: bool,
    expected: list[str],
) -> None:
    """Compare the actual project loader with the guard, without global config."""
    monkeypatch.setenv("LINTRO_GLOBAL_CONFIG", "off")
    config_path = tmp_path / ".lintro-config.yaml"
    source = f"tools:\n{settings}"
    config_path.write_text(source, encoding="utf-8")
    loaded = load_config(config_path=config_path, allow_pyproject_fallback=False)
    assert_that(loaded.tools).contains_only("ruff")
    assert_that(loaded.tools["ruff"].enabled).is_equal_to(enabled)
    assert_that(_policy_violations(source)).is_equal_to(expected)


def test_policy_rejects_undocumented_inherited_disable() -> None:
    """Require a reason when a YAML merge disables a tool implicitly."""
    source = (
        "defaults: &defaults {enabled: false}\ntools:\n  ruff:\n    <<: *defaults\n"
    )
    assert_that(_policy_violations(source)).is_equal_to(
        ["ruff: disabled without a reason"],
    )


@pytest.mark.parametrize(
    ("defaults", "settings", "expected"),
    [
        pytest.param(
            "{enabled: false}",
            "  ruff: # Cost gate.\n    <<: *defaults\n",
            [],
            id="documented-inherited-disable",
        ),
        pytest.param(
            "{enabled: false}",
            "  ruff:\n    <<: *defaults # Cost gate.\n",
            [],
            id="local-merge-inline-reason",
        ),
        pytest.param(
            "{enabled: false}",
            "  ruff:\n    # Cost gate.\n    <<: *defaults\n",
            [],
            id="local-merge-preceding-reason",
        ),
        pytest.param(
            "{enabled: true}",
            "  ruff:\n    <<: *defaults\n",
            [],
            id="inherited-enable",
        ),
        pytest.param(
            "{enabled: false}",
            "  ruff:\n    <<: *defaults\n    enabled: true\n",
            [],
            id="direct-enable-overrides-inherited-disable",
        ),
        pytest.param(
            "{enabled: false}",
            "  ruff:\n    enabled: true\n    <<: *defaults\n",
            [],
            id="direct-enable-before-merge",
        ),
        pytest.param(
            "{enabled: true}",
            "  ruff:\n    <<: *defaults # This merge enables the tool.\n"
            "    enabled: false\n",
            ["ruff: disabled without a reason"],
            id="direct-disable-cannot-borrow-merge-reason",
        ),
        pytest.param(
            "{enabled: false} # Shared defaults.\n",
            "  ruff:\n    <<: *defaults\n",
            ["ruff: disabled without a reason"],
            id="anchor-comment-is-not-local",
        ),
        pytest.param(
            "{enabled: false}",
            "  ruff: *defaults\n",
            ["ruff: disabled without a reason"],
            id="aliased-tool-disable",
        ),
        pytest.param(
            "{enabled: false}",
            "  ruff: *defaults # Cost gate.\n",
            [],
            id="aliased-tool-local-reason",
        ),
        pytest.param(
            "{enabled: false}",
            "  ruff:\n    <<: [*defaults, {enabled: true}]\n",
            ["ruff: disabled without a reason"],
            id="merge-sequence-first-disable-wins",
        ),
        pytest.param(
            "{enabled: false}",
            "  ruff:\n    <<: [{enabled: true}, *defaults]\n",
            [],
            id="merge-sequence-first-enable-wins",
        ),
    ],
)
def test_policy_checks_effective_merged_settings(
    defaults: str,
    settings: str,
    expected: list[str],
) -> None:
    """Check resolved YAML values while requiring tool-local merge reasons."""
    source = f"defaults: &defaults {defaults}\ntools:\n{settings}"
    assert_that(_policy_violations(source)).is_equal_to(expected)


@pytest.mark.parametrize(
    "settings",
    [
        pytest.param(
            "  ruff:\n# Unrelated section.\n    enabled: false\n",
            id="outdented-preceding-comment",
        ),
        pytest.param(
            "  # Unrelated section.\n  ruff:\n    enabled: false\n",
            id="comment-before-tool",
        ),
        pytest.param(
            "  ruff:\n    #\n    enabled: false\n",
            id="empty-preceding-comment",
        ),
        pytest.param(
            "  ruff: {config_source: '# Cost gate.', enabled: false}\n",
            id="quoted-hash-is-not-comment",
        ),
        pytest.param(
            "  ruff:\n    config_source: |\n      # Cost gate.\n    enabled: false\n",
            id="block-scalar-is-not-comment",
        ),
        pytest.param(
            "  {ruff: {enabled: false}, black: {enabled: true}} # Black only.\n",
            id="flow-siblings-cannot-share-comment",
        ),
        pytest.param(
            "  {\n"
            "    ruff: {enabled: false}, black: {enabled: true} # Black only.\n"
            "  }\n",
            id="multiline-flow-siblings-cannot-share-comment",
        ),
    ],
)
def test_policy_rejects_unrelated_reasons(settings: str) -> None:
    """Keep comments from adjacent sections and string content out of scope."""
    assert_that(_policy_violations(f"tools:\n{settings}")).is_equal_to(
        ["ruff: disabled without a reason"],
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("", ["configuration must be a mapping"], id="empty-document"),
        pytest.param("null", ["configuration must be a mapping"], id="null-document"),
        pytest.param("[]", ["configuration must be a mapping"], id="sequence-document"),
        pytest.param("{}", [], id="empty-mapping-defaults-to-enabled"),
        pytest.param("tools:", ["tools must be a mapping"], id="bare-tools-section"),
        pytest.param("tools: []", ["tools must be a mapping"], id="tools-sequence"),
        pytest.param(
            "execution: null",
            ["execution must be a mapping"],
            id="null-execution",
        ),
        pytest.param(
            "tools: {ruff: null}",
            ["ruff: tool configuration must be a mapping or boolean"],
            id="null-tool",
        ),
        pytest.param(
            "tools:\n  ruff:\n",
            ["ruff: tool configuration must be a mapping or boolean"],
            id="bare-tool",
        ),
        pytest.param(
            'tools: {ruff: "false"}',
            ["ruff: tool configuration must be a mapping or boolean"],
            id="string-tool-is-not-boolean-shorthand",
        ),
        pytest.param(
            "tools: {ruff: []}",
            ["ruff: tool configuration must be a mapping or boolean"],
            id="sequence-tool",
        ),
        pytest.param(
            "tools: {ruff: {enabled: null}}",
            ["ruff: invalid tool configuration"],
            id="null-enabled",
        ),
        pytest.param(
            "tools: {ruff: {enabled: never}}",
            ["ruff: invalid tool configuration"],
            id="invalid-enabled",
        ),
        pytest.param(
            "tools: {ruff: {}}", [], id="empty-tool-mapping-defaults-to-enabled"
        ),
        pytest.param("tools: {ruff: true}", [], id="boolean-tool-enable"),
        pytest.param(
            "tools:\n  ruff: false\n",
            ["ruff: disabled without a reason"],
            id="boolean-tool-disable",
        ),
        pytest.param(
            "tools:\n  ruff: false # Cost gate.\n",
            [],
            id="documented-boolean-tool-disable",
        ),
        pytest.param(
            'tools:\n  ruff:\n    enabled: "false"\n',
            ["ruff: disabled without a reason"],
            id="lintro-model-normalizes-enabled",
        ),
        pytest.param(
            "tools: {1: {}}", ["tool name must be a string"], id="nonstring-tool"
        ),
        pytest.param("tools: [", ["invalid YAML configuration"], id="malformed-yaml"),
        pytest.param(
            "tools: {ruff: *unknown}",
            ["invalid YAML configuration"],
            id="undefined-alias",
        ),
    ],
)
def test_policy_validates_lintro_shapes(source: str, expected: list[str]) -> None:
    """Report malformed entries and honor Lintro's mapping/boolean schema."""
    assert_that(_policy_violations(source)).is_equal_to(expected)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("execution: {parallel: true}", []),
        (
            "execution: {enabled_tools: []}",
            ["execution.enabled_tools must be absent"],
        ),
        (
            "execution: {enabled_tools: [ruff]}",
            ["execution.enabled_tools must be absent"],
        ),
        ("tools:\n  ruff:\n    enabled: true\n", []),
        (
            "tools:\n  ruff:\n    enabled: false\n",
            ["ruff: disabled without a reason"],
        ),
        (
            "tools:\n  ruff:\n    enabled: false #\n",
            ["ruff: disabled without a reason"],
        ),
        ("tools:\n  ruff:\n    enabled: false # Cost gate.\n", []),
        ("tools:\n  ruff:\n    enabled: false # Cost gate.", []),
        ("tools:\n  ruff:\n    # Cost gate.\n    enabled: false\n", []),
        (
            (
                "tools:\n  ruff:\n    enabled: true # Unrelated.\n"
                "  black:\n    enabled: false\n"
            ),
            ["black: disabled without a reason"],
        ),
    ],
    ids=[
        "no-allowlist",
        "empty-allowlist",
        "partial-allowlist",
        "enabled-tool",
        "bare-disable",
        "empty-comment",
        "inline-reason",
        "inline-reason-at-eof",
        "preceding-reason",
        "unrelated-comment",
    ],
)
def test_policy_detects_regressions(source: str, expected: list[str]) -> None:
    """Exercise policy failures with small, offline YAML examples."""
    assert_that(_policy_violations(source)).is_equal_to(expected)
