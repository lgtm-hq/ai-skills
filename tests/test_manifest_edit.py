"""Production YAML edits retain scalar semantics and lintable collection layout."""

from collections.abc import Callable
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine.manifest.edit import patch_document
from ai_skills_engine.registry.registry import load_unique_yaml_text

pytest_plugins = ("manifest_helpers",)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("style", ["|", "|-", "|+", ">", ">-", ">+"])
@pytest.mark.parametrize("replacement", ["new", "first\nsecond", "new\n", "it's new"])
def test_changed_block_scalar_retains_following_key(
    style: str, replacement: str
) -> None:
    """Literal and folded scalar ranges must not swallow the next key boundary."""
    text = f"---\na: {style}\n  old\nb: 1\n"
    desired = {"a": replacement, "b": 1}
    result = patch_document(text=text, data=desired)
    assert_that(load_unique_yaml_text(text=result)).is_equal_to(desired)
    assert_that(result).contains("\nb: 1\n")
    assert_that(patch_document(text=result, data=desired)).is_equal_to(result)


@pytest.mark.parametrize("quoted", ["'old'", '"old"', "old"])
@pytest.mark.parametrize(
    "replacement", ["first\nsecond", "it's new", "first\rsecond", "first\n\nsecond\n"]
)
def test_changed_quoted_scalar_retains_exact_value(
    quoted: str, replacement: str
) -> None:
    """Line breaks must be escaped rather than folded inside preserved quotes."""
    text = f"---\na: {quoted} # keep\nb: 1\n"
    desired = {"a": replacement, "b": 1}
    result = patch_document(text=text, data=desired)
    assert_that(load_unique_yaml_text(text=result)).is_equal_to(desired)
    assert_that(result).contains(" # keep\nb: 1\n")
    if quoted == "'old'" and "\n" not in replacement and "\r" not in replacement:
        assert_that(result).contains("'it''s new'")


@pytest.mark.parametrize(
    "text",
    [
        "---\na: |\n  old\nb: 1\n",
        "---\na: >\n  old\nb: 1\n",
        "---\na: 'old' # quote\nb: 1\n",
        '---\na: "old"\nb: 1\n',
        "---\na: &shared [old]\nb: *shared\n",
    ],
)
def test_unchanged_yaml_is_byte_exact(text: str) -> None:
    """No-op edits preserve scalar formatting, comments and safe aliases."""
    assert_that(
        patch_document(text=text, data=load_unique_yaml_text(text=text))
    ).is_equal_to(text)


@pytest.mark.parametrize(
    ("text", "desired"),
    [
        ("---\na:\n  - old\nb: 1\n", {"a": ["old", "new"], "b": 1}),
        ("---\na: [old]\nb: 1\n", {"a": ["old", "new"], "b": 1}),
        ("---\na: {old: 1}\nb: 1\n", {"a": {"new": [1, 2]}, "b": 1}),
        ("---\na:\n  old: 1\nb: 1\n", {"a": {}, "b": 1}),
        ("---\na: []\nb: 1\n", {"a": [{"skills": ["new"]}], "b": 1}),
        (
            "---\na:\n  - old\nb: 1\n",
            {"a": [f"skill-{index}" for index in range(30)], "b": 1},
        ),
        (
            "---\na:\n  - id: old\n    skills: [a]\nb: 1\n",
            {"a": [{"id": "old", "skills": ["a"], "agents": ["reviewer"]}], "b": 1},
        ),
    ],
)
def test_collection_shape_edits_are_lintable(
    text: str, desired: object, tmp_path: Path, check_yaml: Callable[[Path], None]
) -> None:
    """Changed block and inline collections retain indentation and key boundaries."""
    result = patch_document(text=text, data=desired)
    assert_that(load_unique_yaml_text(text=result)).is_equal_to(desired)
    path = tmp_path / "changed.yaml"
    path.write_text(result)
    check_yaml(path)
    assert_that(patch_document(text=result, data=desired)).is_equal_to(result)


def test_ambiguous_alias_and_duplicate_key_edits_fail() -> None:
    """Safe no-op aliases never turn into ambiguous edits or duplicate keys."""
    with pytest.raises(ValueError):
        patch_document(
            text="---\na: &shared [old]\nb: *shared\n",
            data={"a": ["new"], "b": ["different"]},
        )
    with pytest.raises(ValueError):
        patch_document(text="a: old\na: duplicate\n", data={"a": "new"})


def test_nested_long_scalar_replacement_retains_semantics() -> None:
    """Wrapped plain strings remain nested under their original mapping key."""
    desired = {"outer": {"inner": {"a": "a long description " * 12, "b": 1}}}
    result = patch_document(
        text="---\nouter:\n  inner:\n    a: old\n    b: 1\n", data=desired
    )
    assert_that(load_unique_yaml_text(text=result)).is_equal_to(desired)
