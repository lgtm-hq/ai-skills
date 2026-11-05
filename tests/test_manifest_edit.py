"""Production YAML edits retain scalar semantics and lintable collection layout."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

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


@pytest.mark.parametrize("shape", ["root", "mapping", "nested-mapping", "nested-list"])
@pytest.mark.parametrize(
    ("source", "desired"),
    [("true", 1), ("1", True), ("1", 1.0), ("1.0", 1), ("false", 0.0)],
)
def test_equal_valued_scalar_edits_preserve_types(
    shape: str, source: str, desired: object
) -> None:
    """Equal-valued booleans, integers and floats still require real YAML edits."""
    templates = {
        "root": "{value}\n",
        "mapping": "x-value: {value} # preserve\n",
        "nested-mapping": "x-value: {{nested: {value}}} # preserve\n",
        "nested-list": "x-value: [{{nested: [{value}]}}] # preserve\n",
    }
    text = templates[shape].format(value=source)
    replacement = templates[shape].format(value=json.dumps(desired))
    data = load_unique_yaml_text(text=replacement)
    result = patch_document(text=text, data=data)
    # JSON encoding distinguishes types even when Python collection equality does not.
    assert_that(json.dumps(load_unique_yaml_text(text=result))).is_equal_to(
        json.dumps(data)
    )
    assert_that(patch_document(text=result, data=data)).is_equal_to(result)
    if shape != "root":
        assert_that(result).contains(" # preserve\n")


@pytest.mark.parametrize("scalar", ["true", "false", "1", "1.0", "0.0"])
def test_same_type_scalars_preserve_exact_source(scalar: str) -> None:
    """Unchanged scalar types retain root, nested values, quotes and comments."""
    for text in (
        f"{scalar}\n",
        f"x-value: {scalar} # preserve\n",
        f"x-value: {{nested: [{scalar}]}} # preserve\n",
    ):
        assert_that(
            patch_document(text=text, data=load_unique_yaml_text(text=text))
        ).is_equal_to(text)


@pytest.mark.parametrize(
    ("text", "desired"),
    [
        ("false\n", 1),
        ("x-value: false\n", {"x-value": 1}),
        ("x-value: {nested: [false]}\n", {"x-value": {"nested": [1]}}),
    ],
)
def test_final_verification_rejects_equal_value_with_wrong_type(
    text: str, desired: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reload verification must reject a serializer that changes scalar types."""
    monkeypatch.setattr(
        "ai_skills_engine.manifest.edit.yaml.dump",
        lambda *args, **kwargs: "true\n...\n",
    )
    with pytest.raises(ValueError, match="did not preserve the requested values"):
        patch_document(text=text, data=desired)


@pytest.mark.parametrize("quoted", ["'old'", '"old"', "old"])
@pytest.mark.parametrize(
    "replacement",
    ["😀", "first 😀\nsecond", 'say "😀"', "😀\x85end", "😀\u2028end", "😀\u2029end"],
)
def test_unicode_scalar_edits_retain_codepoints(quoted: str, replacement: str) -> None:
    """Quoted and multiline Unicode values must reload as actual codepoints."""
    text = f"x-value: {quoted} # preserve\n"
    desired = {"x-value": replacement}
    result = patch_document(text=text, data=desired)
    assert_that(load_unique_yaml_text(text=result)).is_equal_to(desired)
    assert_that(result).contains(" # preserve\n")
    assert_that(patch_document(text=result, data=desired)).is_equal_to(result)


@pytest.mark.parametrize(
    ("text", "desired"),
    [
        ("items: [{id: one}]\n", {"items": [{"id": "one", "name": "One"}]}),
        ("items: {one: {id: one}}\n", {"items": {"one": {"id": "one", "name": "One"}}}),
        ("items: [{values: [one]}]\n", {"items": [{"values": ["one", "two"]}]}),
        ("items: [{value: one}]\n", {"items": [{"value": {"nested": [True, 1, 1.0]}}]}),
        (
            "items: [{value: {id: one}}]\n",
            {"items": [{"value": ["😀\x85end", "a\u2028b", "line\nend"]}]},
        ),
        ("items: [[{id: one}]]\n", {"items": [[{"id": "one", "name": "😀"}]]}),
    ],
)
def test_nested_flow_shape_changes_preserve_values_and_surrounding_bytes(
    text: str, desired: dict[str, Any]
) -> None:
    """Shape edits stay legal inside flow parents and retain untouched comments."""
    text = "# before\n" + text.rstrip("\n") + " # keep\nother: 'untouched'\n"
    desired = {**desired, "other": "untouched"}
    result = patch_document(text=text, data=desired)
    assert_that(json.dumps(load_unique_yaml_text(text=result))).is_equal_to(
        json.dumps(desired)
    )
    assert_that(result).starts_with("# before\n")
    assert_that(result).ends_with(" # keep\nother: 'untouched'\n")
    assert_that(patch_document(text=result, data=desired)).is_equal_to(result)


def test_flow_alias_shape_changes_fail_closed() -> None:
    """Shared flow nodes cannot silently receive distinct requested shapes."""
    with pytest.raises(ValueError):
        patch_document(
            text="items: [&shared {id: one}, *shared]\n",
            data={"items": [{"id": "one", "name": "One"}, {"id": "one"}]},
        )


def test_matched_block_shape_change_control() -> None:
    """The corresponding normal block mapping still renders correctly."""
    assert_that(
        patch_document(
            text="items:\n  - id: one\n",
            data={"items": [{"id": "one", "name": "One"}]},
        )
    ).is_equal_to("items:\n  - id: one\n    name: One\n")


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("items: [{d: old}]\n", "a, b"),
        ("{d: old}\n", "has } brace"),
        ("{d: old}\n", "x[1]"),
        ("{d: old}\n", "true"),
        ("{d: 'old'}\n", "it's, quoted"),
        ('{d: "old"}\n', 'q, "x"'),
        ("{d: old}\n", "engineering, productivity, and more " * 4),
    ],
    ids=["comma", "brace", "bracket", "bool-like", "single", "double", "long"],
)
def test_flow_parent_scalar_edits_quote_flow_indicators(text: str, value: str) -> None:
    """A string edited inside a flow collection stays one exact flow scalar."""
    data = cast(dict[str, Any], load_unique_yaml_text(text=text))
    target = data["items"][0] if "items" in data else data
    target["d"] = value
    patched = patch_document(text=text, data=data)
    assert_that(load_unique_yaml_text(text=patched)).is_equal_to(data)
    assert_that(patched.removeprefix("items: ")[0]).is_in("[", "{")
    assert_that(patched.count("\n")).is_equal_to(1)


def test_unchanged_flow_parent_plain_scalar_stays_plain() -> None:
    """Flow-safe replacements keep the plain source style."""
    patched = patch_document(text="{d: old, e: 1}\n", data={"d": "new", "e": 1})
    assert_that(patched).is_equal_to("{d: new, e: 1}\n")


@pytest.mark.parametrize("key", ["on", "yes", "1", "1.5", "null"])
def test_non_string_mapping_keys_fail_closed(key: str) -> None:
    """Keys YAML resolves to non-strings fail with a ValueError, not a KeyError."""
    text = f"apiVersion: x\n{key}: true\nvendors: []\n"
    data = cast(dict[str, Any], load_unique_yaml_text(text=text))
    data["vendors"] = ["added"]
    with pytest.raises(ValueError, match="non-string keys"):
        patch_document(text=text, data=data)


def test_merge_keys_are_rejected_as_invalid_yaml() -> None:
    """Merge keys never reach the lossless editor."""
    with pytest.raises(ValueError, match="invalid YAML|merge"):
        patch_document(text="b: &b {x: 1}\nc:\n  <<: *b\n", data={"b": {"x": 2}})


@pytest.mark.parametrize("character", ["\x7f", "\x80", "\x85", "\x9f", "￾"], ids=repr)
@pytest.mark.parametrize("template", ["'old'", '"old"', "old"], ids=repr)
def test_unprintable_characters_are_escaped_not_rejected(
    template: str, character: str
) -> None:
    """DEL and C1 controls round-trip through every scalar quoting style."""
    text = f"key: {template}\nnext: 1\n"
    data = {"key": f"a{character}b", "next": 1}
    patched = patch_document(text=text, data=data)
    assert_that(load_unique_yaml_text(text=patched)).is_equal_to(data)
    assert_that(patched).does_not_contain(character).ends_with("\nnext: 1\n")
    assert_that(patch_document(text=patched, data=data)).is_equal_to(patched)
