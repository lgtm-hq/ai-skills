"""Guard the default-on lintro policy without invoking tools or the network."""

from pathlib import Path

import pytest
import yaml
from assertpy import assert_that


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
    config = yaml.safe_load(source)
    violations = []
    if "enabled_tools" in config.get("execution", {}):
        violations.append("execution.enabled_tools must be absent")

    lines = source.splitlines()
    document = yaml.compose(source)
    for key, tools in document.value:
        if key.value != "tools":
            continue
        for tool, settings in tools.value:
            for setting, value in settings.value:
                if setting.value != "enabled":
                    continue
                if config["tools"][tool.value]["enabled"] is not False:
                    continue
                line_number = value.start_mark.line
                _, _, inline_reason = lines[line_number].partition("#")
                previous = lines[line_number - 1].strip() if line_number else ""
                preceding_reason = (
                    previous[1:].strip() if previous.startswith("#") else ""
                )
                if not (inline_reason.strip() or preceding_reason):
                    violations.append(f"{tool.value}: disabled without a reason")
    return violations


def test_repository_lintro_policy(lintro_source: str) -> None:
    """Keep every future tool enabled and require documented exceptions."""
    assert_that(_policy_violations(lintro_source)).is_empty()


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
        "preceding-reason",
        "unrelated-comment",
    ],
)
def test_policy_detects_regressions(source: str, expected: list[str]) -> None:
    """Exercise policy failures with small, offline YAML examples."""
    assert_that(_policy_violations(source)).is_equal_to(expected)
