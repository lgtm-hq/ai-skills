"""General vendor scalar parity with zero-write rejection and safe writers."""

import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
from assertpy import assert_that
from ci.npm.scalar_helpers import CASES, ROOT, scalar_source

from ai_skills_engine import cli
from ai_skills_engine.manifest.edit import dump_document, patch_document
from ai_skills_engine.manifest.legacy import (
    legacy_documents,
    render_legacy,
    write_legacy,
)
from ai_skills_engine.manifest.load import load_manifest, read_document
from ai_skills_engine.manifest.pins import write_vendors
from ai_skills_engine.registry.registry import load_unique_yaml_text

pytest_plugins = ("manifest_helpers",)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_scalar_source_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: dict[str, Any],
    quote: str,
) -> None:
    """Offline validation rejects divergent plain strings before any output write."""
    path = tmp_path / "ai-skills.yaml"
    path.write_text(scalar_source(case, quote))
    path.chmod(0o640)
    paths = [path, tmp_path / "bundles.yaml", tmp_path / "vendors.yaml"]
    for destination in paths[1:]:
        destination.write_bytes(b"# protected scalar sentinel\r\n")
        destination.chmod(0o600)
    before = {item: (item.read_bytes(), item.stat().st_mode) for item in paths}

    def forbidden(*args: object, **kwargs: object) -> None:
        """Fail on any acquisition/execution or transient publication write."""
        pytest.fail(f"Scalar validation attempted side effects: {args}, {kwargs}")

    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    rejected = case["ambiguous"] and not quote
    args = ["--repo-root", str(tmp_path), "manifest"]
    assert_that(cli.main([*args, "validate"])).is_equal_to(int(rejected))
    if rejected:
        message = f"/vendors/0/{case['field']}"
        assert_that(capsys.readouterr().out).contains(
            message, "unquoted", "PyYAML and Renovate", f"{case['field']}: \""
        )
        for operation in (
            lambda: load_manifest(path),
            lambda: render_legacy(tmp_path),
            lambda: write_legacy(tmp_path),
            lambda: write_legacy(tmp_path, check=True),
        ):
            with pytest.raises(ValueError, match=message):
                operation()
        for command in (["legacy"], ["legacy", "--check"]):
            assert_that(cli.main([*args, *command])).is_equal_to(1)
    else:
        vendor = load_manifest(path).vendors[0]
        assert_that(getattr(vendor, case["field"])).is_equal_to(case["value"])
    assert_that(
        {item: (item.read_bytes(), item.stat().st_mode) for item in paths}
    ).is_equal_to(before)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_scalar_writers_preserve_strings(tmp_path: Path, case: dict[str, Any]) -> None:
    """Fresh, template and management writers retain identical string values."""
    quoted = scalar_source(case, '"')
    path = tmp_path / "ai-skills.yaml"
    path.write_text(quoted)
    data = read_document(path)
    fresh = dump_document(data)
    patched = patch_document(text=scalar_source(case), data=data)
    for source in (fresh, patched):
        path.write_text(source)
        assert_that(read_document(path)).is_equal_to(data)
    # Management's scalar and collection replacement paths must both quote pins.
    # Copy real first-party payloads only; no vendor source is acquired/executed.
    shutil.copytree(src=ROOT / "skills", dst=tmp_path / "skills")
    path.write_bytes((ROOT / "ai-skills.yaml").read_bytes())
    vendors = legacy_documents(read_document(path))["vendors.yaml"]["vendors"]
    vendors[0][case["field"]] = case["value"]
    if not case["publish"]:
        before = (path.read_bytes(), path.stat().st_mode)
        with pytest.raises(ValueError, match="branch"):
            write_vendors(path, vendors)
        assert_that((path.read_bytes(), path.stat().st_mode)).is_equal_to(before)
        return
    write_vendors(path, vendors)
    assert_that(getattr(load_manifest(path).vendors[0], case["field"])).is_equal_to(
        case["value"]
    )
    assert_that(write_legacy(tmp_path, check=True)).is_zero()
    vendors[0].pop("displayRef", None)
    write_vendors(path, vendors)
    assert_that(getattr(load_manifest(path).vendors[0], case["field"])).is_equal_to(
        case["value"]
    )


@pytest.mark.parametrize(
    "source",
    ["!!str 0o17", "! 0o17", "&branch '0o17'", ">-\n      0o17", "|-\n      0o17"],
)
def test_non_plain_branch_spellings_stay_valid(tmp_path: Path, source: str) -> None:
    """Explicit strings, anchors and block branches keep their existing contract."""
    path = tmp_path / "ai-skills.yaml"
    path.write_text(
        "apiVersion: ai-skills.dev/v1\npublisher: {id: example}\nexports: []\n"
        "vendors:\n  - id: first\n    repo: owner/first\n"
        f"    sha: {'a' * 40}\n    branch: {source}\n"
    )
    assert_that(load_manifest(path).vendors[0].branch).is_equal_to("0o17")


@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_aliased_branch_scalar_parity(tmp_path: Path, quote: str) -> None:
    """Branch aliases stay supported when their source scalar is unambiguous."""
    path = tmp_path / "ai-skills.yaml"
    source = (
        f"x-branch: &branch {quote}0o17{quote}\n"
        "apiVersion: ai-skills.dev/v1\npublisher: {id: example}\nexports: []\n"
        f"vendors: [{{id: first, repo: owner/first, sha: {'a' * 40}, "
        "branch: *branch}]\n"
    )
    path.write_text(source)
    if quote:
        assert_that(load_manifest(path).vendors[0].branch).is_equal_to("0o17")
    else:
        with pytest.raises(ValueError, match="/vendors/0/branch"):
            load_manifest(path)
        desired = load_unique_yaml_text(text=source)
        path.write_text(patch_document(text=source, data=desired))
        assert_that(load_manifest(path).vendors[0].branch).is_equal_to("0o17")


@pytest.mark.parametrize("separator", ["\x85", "\u2028", "\u2029"])
def test_unicode_line_break_scalar_parity(tmp_path: Path, separator: str) -> None:
    """Plain YAML 1.1 line folding is rejected and writers escape exact strings."""
    path = tmp_path / "ai-skills.yaml"
    source = (
        "apiVersion: ai-skills.dev/v1\npublisher: {id: example}\nexports: []\n"
        "vendors:\n  - id: first\n    repo: owner/first\n"
        f"    sha: {'a' * 40}\n    branch: main{separator}      next\n"
    )
    desired = cast(dict[str, Any], load_unique_yaml_text(text=source))
    path.write_text(source)
    with pytest.raises(ValueError, match="/vendors/0/branch"):
        load_manifest(path)
    for rendered in (dump_document(desired), patch_document(text=source, data=desired)):
        path.write_text(rendered)
        assert_that(read_document(path)).is_equal_to(desired)
    # Also preserve a requested NEL itself, before PyYAML's emitter folds it.
    desired["vendors"][0]["branch"] = f"main{separator}next"
    rendered = dump_document(desired)
    path.write_text(rendered)
    assert_that(read_document(path)).is_equal_to(desired)
    assert_that(rendered).contains(json.dumps(desired["vendors"][0]["branch"]))


@pytest.mark.parametrize("separator", ["\x85", "\u2028", "\u2029"])
def test_aliased_branch_unicode_prefix(tmp_path: Path, separator: str) -> None:
    """Aliases inspect the original scalar's lexical prefix as well as its value."""
    source = (
        f"x-branch: {separator}  &branch main\n"
        "apiVersion: ai-skills.dev/v1\npublisher: {id: example}\nexports: []\n"
        f"vendors: [{{id: first, repo: owner/first, sha: {'a' * 40}, "
        "branch: *branch}]\n"
    )
    path = tmp_path / "ai-skills.yaml"
    path.write_text(source)
    with pytest.raises(ValueError, match="/vendors/0/branch"):
        load_manifest(path)
    data = load_unique_yaml_text(text=source)
    path.write_text(patch_document(text=source, data=data))
    assert_that(load_manifest(path).vendors[0].branch).is_equal_to("main")
