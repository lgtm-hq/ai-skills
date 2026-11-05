"""Mandatory production Renovate discovery and SHA-update regressions, offline."""

from __future__ import annotations

import json
from collections.abc import Callable
from itertools import permutations
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.manifest.legacy import (
    legacy_documents,
    render_legacy,
    write_legacy,
)
from ai_skills_engine.manifest.load import load_manifest, read_document
from ai_skills_engine.registry.registry import load_registry, load_unique_yaml_text
from ai_skills_engine.vendors import manage as manage_vendors

if TYPE_CHECKING:
    from renovate_helpers import VendorPinMatch

pytest_plugins = ("renovate_helpers",)
ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests/fixtures/manifest"
_NEW_HEAD = "a" * 40


@pytest.mark.parametrize("branches", [("main", "main"), ("main", "next")])
def test_duplicate_vendor_digests_keep_distinct_occurrence_spans(
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
    branches: tuple[str, str],
) -> None:
    """Equal pins belong to their own vendor records in extraction order."""
    digest = "a" * 40
    text = "vendors:\n" + "".join(
        f"- id: vendor-{index}\n  repo: owner/shared\n"
        f"  sha: '{digest}'\n  branch: {branch}\n"
        for index, branch in enumerate(branches)
    )
    matches = vendor_pin_matches(text)
    assert_that(matches).is_length(2)
    starts = [text.index(digest), text.rindex(digest)]
    assert_that([match.span("currentDigest") for match in matches]).is_equal_to(
        [(start, start + len(digest)) for start in starts]
    )


@pytest.fixture
def legacy_repo(tmp_path: Path, author_skills: None) -> Path:
    """Copy pre-migration registries and real author payloads without acquisition."""
    for name in ("bundles.yaml", "vendors.yaml"):
        (tmp_path / name).write_bytes((FIXTURES / "legacy" / name).read_bytes())
    return tmp_path


@pytest.mark.parametrize("indent", [0, 1, 2, 3, 4, 6, 8, 10, 23, 100])
def test_renovate_matches_manifest_and_regeneration(
    legacy_repo: Path,
    indent: int,
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
    renovate_run: Callable[..., dict[str, Any]],
) -> None:
    """The actual custom manager extracts and edits every authoritative pin."""
    assert_that(
        cli.main(["--repo-root", str(legacy_repo), "manifest", "migrate"])
    ).is_zero()
    manager = next(
        item
        for item in json.loads((ROOT / "renovate.json").read_text())["customManagers"]
        if item.get("datasourceTemplate") == "git-refs"
    )
    assert_that(manager["managerFilePatterns"]).is_equal_to([r"/^ai-skills\.yaml$/"])
    path = legacy_repo / "ai-skills.yaml"
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    in_vendors = False
    for index, line in enumerate(lines):
        if line.startswith("vendors:"):
            in_vendors = True
        elif in_vendors and line.startswith(" "):
            lines[index] = " " * indent + line[2:]
        elif in_vendors and line.strip():
            in_vendors = False
    text = "".join(lines)
    assert_that(read_document(path)).is_equal_to(load_unique_yaml_text(text=text))
    matches = vendor_pin_matches(text)
    vendors = load_registry(registry_path=legacy_repo / "vendors.yaml")
    assert_that(
        [
            (item["depName"], item["currentDigest"], item["currentValue"])
            for item in matches
        ]
    ).is_equal_to([(vendor.repo, vendor.sha, vendor.branch) for vendor in vendors])
    result = renovate_run(
        text,
        json.dumps(
            [
                {"depIndex": index, "newDigest": "f" * 40}
                for index in range(len(matches))
            ]
        ),
    )
    assert_that(result["updateErrors"]).is_empty()
    text = result["content"]
    path.write_text(text)
    assert_that(
        cli.main(["--repo-root", str(legacy_repo), "manifest", "legacy"])
    ).is_zero()
    assert_that(
        {
            vendor.sha
            for vendor in load_registry(registry_path=legacy_repo / "vendors.yaml")
        }
    ).is_equal_to({"f" * 40})


def test_native_discovery_after_management_writer_add_and_update(
    legacy_repo: Path,
    renovate_run: Callable[..., dict[str, Any]],
) -> None:
    """The real management writer preserves discovery for edited and added pins."""
    assert_that(
        cli.main(["--repo-root", str(legacy_repo), "manifest", "migrate"])
    ).is_zero()
    path = legacy_repo / "ai-skills.yaml"
    vendors = legacy_documents(read_document(path))["vendors.yaml"]["vendors"]
    vendors[0].update(sha="a" * 40, branch="release/next")
    vendors.append(
        manage_vendors._build_vendor_mapping(
            vendor_id="brand-new",
            repo="owner/brand-new",
            sha="b" * 40,
            branch="main",
            skill_roots=("skills",),
            license_name="MIT",
            homepage="https://github.com/owner/brand-new",
            display_ref=None,
        )
    )
    manage_vendors._write_registry(
        registry_path=path,
        vendors=vendors,
    )
    source = path.read_text()
    result = renovate_run(
        source,
        json.dumps(
            [
                {"depIndex": len(vendors) - 1, "newDigest": "f" * 40},
            ]
        ),
    )
    assert_that(result["deps"][0]["currentValue"]).is_equal_to("release/next")
    assert_that(result["deps"][-1]["depName"]).is_equal_to("owner/brand-new")
    assert_that(result["content"]).is_equal_to(source.replace("b" * 40, "f" * 40))
    assert_that(result["updateErrors"]).is_empty()


@pytest.mark.parametrize("indent", [0, 1, 2, 3, 4, 6, 8, 10, 23, 100])
@pytest.mark.parametrize("order", list(permutations(("id", "repo", "sha", "branch"))))
@pytest.mark.parametrize("comments", [False, True])
def test_renovate_extracts_reordered_vendor_records(
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
    renovate_run: Callable[..., dict[str, Any]],
    indent: int,
    order: tuple[str, ...],
    comments: bool,
) -> None:
    """Native extraction preserves vendor fields across reordering and comments."""
    records = []
    expected = []
    for name, digest in (("first", "a" * 40), ("second", "b" * 40)):
        fields = {
            "id": name,
            "repo": f'"owner/{name}"',
            "sha": f"'{digest}'",
            "branch": "'release/next'",
        }
        lines = [f"{' ' * indent}- {order[0]}: {fields[order[0]]}\n"]
        for key in order[1:]:
            if comments:
                lines.extend(["\n", f"{' ' * (indent + 2)}# repo: ignored/comment\n"])
            lines.append(f"{' ' * (indent + 2)}{key}: {fields[key]} # tracked\n")
        records.append("".join(lines))
        expected.append(
            {
                "depName": f"owner/{name}",
                "currentDigest": digest,
                "currentValue": "release/next",
            }
        )
    text = "vendors: # declarations\n" + "".join(records) + "exports: []\n"
    # Both layouts are real YAML, before native discovery and updater checks.
    document = load_unique_yaml_text(text=text)
    if not isinstance(document, dict):
        raise TypeError("Fixture manifest must be a mapping")
    assert_that(document["vendors"]).is_length(2)
    matches = vendor_pin_matches(text)
    assert_that([match.groupdict() for match in matches]).is_equal_to(expected)
    for match in matches:
        start, end = match.span("currentDigest")
        assert_that(text[start:end]).is_equal_to(match["currentDigest"])
    result = renovate_run(text, json.dumps([{"depIndex": 1, "newDigest": "f" * 40}]))
    assert_that(result["content"]).is_equal_to(text.replace("b" * 40, "f" * 40))
    assert_that(result["updateErrors"]).is_empty()


@pytest.mark.parametrize("indent", [0, 1, 2, 3, 4, 6, 8, 10, 23, 100])
@pytest.mark.parametrize("missing", ["repo", "sha", "branch", "none"])
def test_renovate_never_borrows_fields_outside_vendor_record(
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
    indent: int,
    missing: str,
) -> None:
    """Nested mappings, adjacent vendors and later top-level sequences stay isolated."""
    pad = " " * (indent + 2)
    nested = pad + "  "
    fields = {"repo": "owner/first", "sha": "a" * 40, "branch": "main"}
    text = "vendors:\n" + " " * indent + "- id: first\n"
    text += (
        f"{pad}mapping:\n{nested}repo: ignored/mapping\n"
        f"{nested}sha: {'d' * 40}\n{nested}branch: hidden\n"
        f"{nested}packages:\n{nested}  - id: nested\n"
        f"{nested}    repo: ignored/nested\n"
        f"{nested}    sha: {'e' * 40}\n{nested}    branch: hidden\n"
    )
    text += "".join(
        f"{pad}{key}: {value}\n" for key, value in fields.items() if key != missing
    )
    text += (
        f"{' ' * indent}- id: second\n{pad}repo: owner/second\n"
        f"{pad}sha: {'b' * 40}\n{pad}branch: next\n"
        "x-other:\n- id: other\n  repo: ignored/top-level\n"
        f"  sha: {'c' * 40}\n  branch: hidden\n"
    )
    document = load_unique_yaml_text(text=text)
    if not isinstance(document, dict):
        raise TypeError("Fixture manifest must be a mapping")
    assert_that(document["vendors"]).is_length(2)
    expected = []
    if missing == "none":
        expected.append(
            {
                "depName": "owner/first",
                "currentDigest": "a" * 40,
                "currentValue": "main",
            }
        )
    expected.append(
        {"depName": "owner/second", "currentDigest": "b" * 40, "currentValue": "next"}
    )
    assert_that([match.groupdict() for match in vendor_pin_matches(text)]).is_equal_to(
        expected
    )


def test_renovate_ignores_mapping_templates_and_unrelated_repos(
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
) -> None:
    """Only vendor item headers declare dependencies, not incidental repo fields."""
    text = (
        "publisher:\n    repo: irrelevant/publisher\n"
        f"    sha: {'a' * 40}\n    branch: main\n"
        "vendors:\n  - id: real-vendor\n    repo: example/real\n"
        f"    sha: {'b' * 40}\n    branch: main # tracked\n"
        "    mapping:\n      repo: irrelevant/mapping\n"
        f"      sha: {'c' * 40}\n      branch: hidden\n"
        "x-template: |\n    repo: irrelevant/template\n"
        f"    sha: {'d' * 40}\n    branch: hidden\n"
        "x-unrelated:\n  - id: unrelated\n    repo: irrelevant/other\n"
        f"    sha: {'e' * 40}\n    branch: hidden\n"
    )
    matches = vendor_pin_matches(text)
    assert_that([match["depName"] for match in matches]).is_equal_to(["example/real"])


@pytest.fixture
def renovate_vendor_manager() -> dict[str, Any]:
    """Read the actual Renovate manager for vendor refs.

    Returns:
        The git-refs custom manager configuration.
    """
    config = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))
    return next(
        item
        for item in config["customManagers"]
        if item.get("datasourceTemplate") == "git-refs"
    )


def test_renovate_captures_every_explicit_vendor_branch(
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
    renovate_vendor_manager: dict[str, Any],
) -> None:
    """The actual Renovate YAML manager extracts all pins and their branch refs."""
    matches = [
        match.groupdict()
        for match in vendor_pin_matches(
            (ROOT / "vendors.yaml").read_text(encoding="utf-8")
        )
    ]
    vendors = load_registry(registry_path=ROOT / "vendors.yaml")
    assert_that(matches).is_equal_to(
        [
            {
                "depName": vendor.repo,
                "currentDigest": vendor.sha,
                "currentValue": vendor.branch,
            }
            for vendor in vendors
        ],
    )
    assert_that(len(matches)).is_equal_to(5)
    assert_that(renovate_vendor_manager).does_not_contain_key("currentValueTemplate")
    for vendor in vendors:
        assert_that(vendor.branch).is_equal_to("main")


@pytest.mark.parametrize(
    "branch",
    [
        "main",
        "release/next",
        "123",
        "1.2",
        "true",
        "False",
        "yes",
        "null",
        "2026-10-31",
    ],
    ids=[
        "plain",
        "slash",
        "integer",
        "decimal",
        "true",
        "false",
        "yes",
        "null",
        "date",
    ],
)
def test_renovate_captures_registry_writer_branch(
    tmp_path: Path,
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
    branch: str,
) -> None:
    """Capture branch names without the quotes emitted by the registry writer."""
    registry_path = tmp_path / "vendors.yaml"
    vendor = manage_vendors._build_vendor_mapping(
        vendor_id="example",
        repo="owner/example",
        sha=_NEW_HEAD,
        branch=branch,
        skill_roots=("skills",),
        license_name="MIT",
        homepage="https://github.com/owner/example",
        display_ref=None,
    )
    manage_vendors._write_registry(registry_path=registry_path, vendors=[vendor])
    matches = vendor_pin_matches(registry_path.read_text(encoding="utf-8"))

    assert_that(load_registry(registry_path=registry_path)[0].branch).is_equal_to(
        branch
    )
    assert_that(matches).is_length(1)
    assert_that(matches[0].groupdict()).is_equal_to(
        {
            "depName": "owner/example",
            "currentDigest": _NEW_HEAD,
            "currentValue": branch,
        },
    )


@pytest.mark.parametrize(
    "branch_scalar", ["release/next", "'release/next'", '"release/next"']
)
@pytest.mark.parametrize(
    "comment",
    ["", " # upstream default", "\t # upstream 'default' (\"main\")"],
    ids=["no-comment", "space-comment", "tab-comment-with-quotes"],
)
@pytest.mark.parametrize("line_ending", ["\n", "\r\n", ""], ids=["lf", "crlf", "eof"])
def test_renovate_captures_yaml_branch_quote_styles(
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
    branch_scalar: str,
    comment: str,
    line_ending: str,
) -> None:
    """Capture complete YAML scalars with optional comments and line endings."""
    text = (
        "vendors:\n  - id: example\n"
        f'    repo: owner/example\n    sha: "{_NEW_HEAD}"\n'
        f"    branch: {branch_scalar}{comment}{line_ending}"
    )
    matches = vendor_pin_matches(text)

    assert_that(matches).is_length(1)
    assert_that(matches[0].groupdict()).is_equal_to(
        {
            "depName": "owner/example",
            "currentDigest": _NEW_HEAD,
            "currentValue": "release/next",
        },
    )


@pytest.mark.parametrize("branch", ["it's", 'embedded"quote', "both'\"quotes"])
@pytest.mark.parametrize("comment", ["", " # upstream default"])
@pytest.mark.parametrize("line_ending", ["\n", "\r\n", ""], ids=["lf", "crlf", "eof"])
def test_renovate_never_truncates_branch_quotes(
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
    branch: str,
    comment: str,
    line_ending: str,
) -> None:
    """Decode complete valid scalars; malformed YAML cannot truncate a ref."""
    for scalar in [branch, f"'{branch}'", json.dumps(branch)]:
        text = (
            "vendors:\n  - id: example\n"
            f'    repo: owner/example\n    sha: "{_NEW_HEAD}"\n'
            f"    branch: {scalar}{comment}{line_ending}"
        )
        try:
            yaml.safe_load(text)
        except yaml.YAMLError:
            assert_that(vendor_pin_matches(text)).is_empty()
        else:
            assert_that(
                [match["currentValue"] for match in vendor_pin_matches(text)]
            ).is_equal_to([branch])


@pytest.mark.parametrize(
    "branch_scalar, expected",
    [
        ("'main''suffix'", "main'suffix"),
        ('"main"suffix"', None),
        ("main'bad", "main'bad"),
    ],
)
@pytest.mark.parametrize("line_ending", ["\n", "\r\n", ""], ids=["lf", "crlf", "eof"])
def test_renovate_preserves_scalar_boundaries(
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
    branch_scalar: str,
    expected: str | None,
    line_ending: str,
) -> None:
    """Native parsing preserves embedded quotes and rejects malformed YAML."""
    text = (
        "vendors:\n  - id: example\n"
        f'    repo: owner/example\n    sha: "{_NEW_HEAD}"\n'
        f"    branch: {branch_scalar}{line_ending}"
    )
    matches = vendor_pin_matches(text)
    assert_that([match["currentValue"] for match in matches]).is_equal_to(
        [] if expected is None else [expected]
    )


@pytest.mark.parametrize(
    "branch_scalar",
    ['"main', "'main", 'main"', "main'", "'main\"", "\"main'"],
)
@pytest.mark.parametrize("comment", ["", " # upstream 'default'"])
def test_registry_rejects_unbalanced_quotes_permitted_by_renovate(
    tmp_path: Path,
    vendor_pin_matches: Callable[[str], list[VendorPinMatch]],
    branch_scalar: str,
    comment: str,
) -> None:
    """Native discovery never truncates scalars; the legacy registry rejects quotes."""
    registry = tmp_path / "vendors.yaml"
    registry.write_text(
        "vendors:\n"
        "  - id: example\n"
        "    repo: owner/example\n"
        f'    sha: "{_NEW_HEAD}"\n'
        f"    branch: {branch_scalar}{comment}\n"
        "    skillRoots: [skills]\n"
        "    license: MIT\n"
        "    homepage: https://github.com/owner/example\n",
        encoding="utf-8",
    )
    matches = vendor_pin_matches(registry.read_text(encoding="utf-8"))
    assert_that([match["currentValue"] for match in matches]).is_equal_to(
        [branch_scalar] if branch_scalar in {'main"', "main'"} else [],
    )
    with pytest.raises((yaml.YAMLError, ValueError)):
        load_registry(registry_path=registry)


OLD = "a" * 40
NEW = "f" * 40


def _document(records: str) -> str:
    """Wrap records in a structurally and semantically valid manifest."""
    return (
        "apiVersion: ai-skills.dev/v1\npublisher: {id: example}\n"
        f"vendors:\n{records}exports: []\n"
    )


@pytest.mark.parametrize("spelling", ["escaped-sha", "shared-anchor"])
def test_native_update_requires_direct_sha_source(
    tmp_path: Path,
    renovate_run: Callable[..., dict[str, Any]],
    spelling: str,
) -> None:
    """Bypassing validation either cannot replace escapes or updates both aliases."""
    scalar = '"' + r"\u0061" * 40 + '"' if spelling == "escaped-sha" else "*pin"
    text = _document(
        "".join(
            f"  - id: {name}\n    repo: owner/{name}\n"
            f"    sha: {scalar}\n    branch: main\n"
            for name in ("first", "second")
        ),
    )
    if spelling == "shared-anchor":
        text = f'x-pin: &pin "{OLD}"\n' + text
    result = renovate_run(text, json.dumps([{"depIndex": 1, "newDigest": NEW}]))
    assert_that([dep["currentDigest"] for dep in result["deps"]]).is_equal_to(
        [OLD, OLD]
    )
    if spelling == "escaped-sha":
        assert_that(result["updates"]).is_equal_to([text])
        assert_that(result["content"]).is_equal_to(text)
    else:
        assert_that(result["updates"]).is_equal_to([text.replace(OLD, NEW)])
        updated = load_unique_yaml_text(text=result["content"])
        if not isinstance(updated, dict):
            raise TypeError("Fixture manifest must be a mapping")
        assert_that([vendor["sha"] for vendor in updated["vendors"]]).is_equal_to(
            [NEW, NEW]
        )
    path = tmp_path / "ai-skills.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="direct, unescaped 40-hex scalar"):
        load_manifest(path)


@pytest.mark.parametrize(
    "indent, order, escaped_repo",
    [
        (1, ("id", "repo", "sha", "branch"), False),
        (3, ("id", "repo", "sha", "branch"), False),
        (5, ("id", "repo", "sha", "branch"), False),
        (23, ("id", "repo", "sha", "branch"), False),
        (0, ("id", "repo", "sha", "branch"), False),
        (2, ("id", "sha", "repo", "branch"), False),
        (2, ("id", "repo", "sha", "branch"), True),
    ],
    ids=[
        "indent-one",
        "indent-three",
        "indent-five",
        "deep-indentation",
        "indentless-sequence",
        "sha-before-repo",
        "escaped-repo",
    ],
)
def test_owner_discovery_controls(
    tmp_path: Path,
    renovate_run: Callable[..., dict[str, Any]],
    indent: int,
    order: tuple[str, ...],
    escaped_repo: bool,
) -> None:
    """Each discovery finding reaches the real extractor and isolated updater."""
    records = []
    for name in ("first", "second"):
        fields = {
            "id": name,
            "repo": f'"\\u006fwner/{name}"' if escaped_repo else f"owner/{name}",
            "sha": f'"{OLD}"',
            "branch": "main",
        }
        records.append(" " * indent + f"- {order[0]}: {fields[order[0]]}\n")
        records.extend(
            " " * (indent + 2) + f"{key}: {fields[key]} # preserve\n"
            for key in order[1:]
        )
    text = _document("".join(records))
    path = tmp_path / "ai-skills.yaml"
    path.write_text(text)
    load_manifest(path)
    result = renovate_run(text, json.dumps([{"depIndex": 1, "newDigest": NEW}]))
    assert_that([dep["depName"] for dep in result["deps"]]).is_equal_to(
        ["owner/first", "owner/second"]
    )
    expected = text.rsplit(OLD, 1)
    assert_that(result["content"]).is_equal_to(NEW.join(expected))
    assert_that(result["updateErrors"]).is_empty()


def test_reordered_quoted_keys_remain_valid(
    tmp_path: Path,
    renovate_run: Callable[..., dict[str, Any]],
) -> None:
    """Field order and key spelling are YAML structure, not regex conventions."""
    text = _document(
        f"  - id: first\n    'sha': '{OLD}'\n"
        '    "repo": owner/first\n    branch: main\n',
    )
    path = tmp_path / "ai-skills.yaml"
    path.write_text(text)
    load_manifest(path)
    result = renovate_run(text, json.dumps([{"depIndex": 0, "newDigest": NEW}]))
    assert_that([dep["depName"] for dep in result["deps"]]).is_equal_to(["owner/first"])
    assert_that(result["content"]).is_equal_to(text.replace(OLD, NEW))
    assert_that(result["updateErrors"]).is_empty()


@pytest.mark.parametrize(
    "repo, branch",
    [
        ("&repository owner/first", "!!str main"),
        (">-\n      owner/first", ">-\n      main"),
        ("'owner/first'", '"release/\\u006eext"'),
        ("!!str owner/first", "'main''suffix'"),
    ],
    ids=["anchor-and-tag", "block-scalars", "escaped-branch", "embedded-quote"],
)
def test_non_sha_spellings_remain_permissive(
    tmp_path: Path,
    renovate_run: Callable[..., dict[str, Any]],
    repo: str,
    branch: str,
) -> None:
    """The SHA contract adds no source restrictions to repo or branch fields."""
    text = _document(
        f"  - id: first\n    sha: '{OLD}'\n"
        f"    repo: {repo}\n    branch: {branch}\n",
    )
    path = tmp_path / "ai-skills.yaml"
    path.write_text(text)
    vendor = load_manifest(path).vendors[0]
    result = renovate_run(text, json.dumps([{"depIndex": 0, "newDigest": NEW}]))
    assert_that(result["matches"][0]["groups"]).is_equal_to(
        {
            "depName": vendor.repo,
            "currentValue": vendor.branch,
            "currentDigest": OLD,
        }
    )
    assert_that(result["content"]).is_equal_to(text.replace(OLD, NEW))
    assert_that(result["updateErrors"]).is_empty()


@pytest.mark.parametrize("indent", [0, 1, 2, 3, 8, 10, 23, 100])
@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_production_digest_updates_are_isolated(
    tmp_path: Path,
    renovate_run: Callable[..., dict[str, Any]],
    indent: int,
    quote: str,
) -> None:
    """Actual auto-replace retries decoys and changes only the targeted vendor SHA."""
    pad = " " * indent
    fields = pad + "  "
    records = ""
    for name in ("first", "second"):
        records += (
            f"{pad}- branch: main # reordered\n"
            f"{fields}x-decoy: {{repo: owner/decoy, sha: '{OLD}', branch: hidden}}\n"
            f"{fields}repo: owner/{name}\n"
            f"{fields}# keep this comment with the same digest {OLD}\n"
            f"{fields}sha: {quote}{OLD}{quote} # tracked {name}\n"
            f"{fields}id: {name}\n"
        )
    text = f"# leading digest decoy {OLD}\n" + _document(records)
    path = tmp_path / "ai-skills.yaml"
    path.write_text(text)
    load_manifest(path)
    result = renovate_run(text, json.dumps([{"depIndex": 1, "newDigest": NEW}]))
    expected = text.replace(
        f"sha: {quote}{OLD}{quote} # tracked second",
        f"sha: {quote}{NEW}{quote} # tracked second",
    )
    assert_that(result["updates"]).is_equal_to([expected])
    assert_that(result["content"]).is_equal_to(expected)
    assert_that(result["deps"]).is_length(2)
    assert_that(result["deps"][1]["packageName"]).is_equal_to(
        "https://github.com/owner/second"
    )
    assert_that(result["deps"][1]["datasource"]).is_equal_to("git-refs")
    path.write_text(expected)
    load_manifest(path)


@pytest.mark.parametrize(
    "record",
    [
        f'  - {{id: first, sha: "{OLD}", repo: "owner/first", branch: main}}\n',
        (
            '  - id: first\n    repo: "\\u006fwner/first"\n'
            f'    sha: "{OLD}"\n    branch: "ma\\u0069n"\n'
        ),
        (
            "  - id: first\n    repo: 'owner/first'\n"
            f"    sha: '{OLD}'\n    branch: 'release/next'\n"
        ),
    ],
    ids=["flow-record", "escaped-repo-and-branch", "single-quoted"],
)
def test_native_scalar_decoding_and_digest_update(
    tmp_path: Path,
    renovate_run: Callable[..., dict[str, Any]],
    record: str,
) -> None:
    """Real JSONata decodes scalar spellings and real auto-replace preserves layout."""
    text = _document(record)
    path = tmp_path / "ai-skills.yaml"
    path.write_text(text)
    manifest = load_manifest(path)
    result = renovate_run(text, json.dumps([{"depIndex": 0, "newDigest": NEW}]))
    assert_that(result["matches"][0]["groups"]).is_equal_to(
        {
            "depName": "owner/first",
            "currentDigest": OLD,
            "currentValue": manifest.vendors[0].branch,
        },
    )
    assert_that(result["updates"]).is_equal_to([text.replace(OLD, NEW)])


@pytest.mark.parametrize("line_ending", ["\n", "\r\n", ""])
def test_unseparated_comment_production_parser_differential(
    tmp_path: Path,
    renovate_run: Callable[..., dict[str, Any]],
    line_ending: str,
) -> None:
    """Renovate accepts the literal; manifest validation rejects it before writes."""
    root = tmp_path
    text = (
        (ROOT / "ai-skills.yaml")
        .read_text()
        .replace(
            "branch: main\n",
            'branch: "main"#no-separation' + line_ending,
            1,
        )
    )
    # EOF is tested on an isolated minimal manifest to keep the literal at EOF.
    if line_ending == "":
        text = _document(
            f'  - id: first\n    repo: owner/first\n    sha: "{OLD}"\n'
        ).replace("exports: []\n", '    branch: "main"#no-separation')
    path = root / "ai-skills.yaml"
    path.write_text(text)
    result = renovate_run(text)
    assert_that(result["matches"]).is_not_empty()
    assert_that(result["matches"][0]["groups"]["currentValue"]).is_equal_to("main")
    sentinels = {
        root / name: f"sentinel {name}\n".encode()
        for name in ("bundles.yaml", "vendors.yaml")
    }
    for destination, raw in sentinels.items():
        destination.write_bytes(raw)
    with pytest.raises(
        ValueError, match="comments after quoted scalars require whitespace"
    ):
        load_manifest(path)
    with pytest.raises(
        ValueError, match="comments after quoted scalars require whitespace"
    ):
        render_legacy(root)
    with pytest.raises(
        ValueError, match="comments after quoted scalars require whitespace"
    ):
        write_legacy(repo_root=root, check=False)
    args = ["--repo-root", str(root), "manifest"]
    assert_that(cli.main([*args, "validate"])).is_equal_to(1)
    assert_that(cli.main([*args, "legacy"])).is_equal_to(1)
    assert_that(cli.main([*args, "legacy", "--check"])).is_equal_to(1)
    for destination, raw in sentinels.items():
        assert_that(destination.read_bytes()).is_equal_to(raw)
