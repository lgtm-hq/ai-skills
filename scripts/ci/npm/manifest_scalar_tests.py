"""Mandatory scalar parity at the actual pinned extractor/updater boundary."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from assertpy import assert_that
from scalar_helpers import CASES, line_break_source, scalar_source

from ai_skills_engine.manifest.edit import dump_document, patch_document
from ai_skills_engine.manifest.legacy import write_legacy
from ai_skills_engine.manifest.load import load_manifest, read_document
from ai_skills_engine.registry.registry import load_unique_yaml_text

pytest_plugins = ("renovate_helpers",)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize(("indent", "reverse"), [(0, False), (3, True), (23, True)])
def test_actual_scalar_extraction_publication_and_isolated_update(
    tmp_path: Path,
    renovate_run: Callable[..., dict[str, Any]],
    case: dict[str, Any],
    indent: int,
    reverse: bool,
) -> None:
    """Keep real RED controls, then validate/publish/update quoted and writer output."""
    (tmp_path / "skills").mkdir()
    path = tmp_path / "ai-skills.yaml"
    plain = scalar_source(case, indent=indent, reverse=reverse)
    path.write_text(plain)
    path.chmod(0o640)
    snapshot = (path.read_bytes(), path.stat().st_mode)
    raw = renovate_run(plain)
    if case["ambiguous"]:
        # The actual production query drops the target before the boundary fix.
        assert_that([item["depName"] for item in raw["deps"]]).does_not_contain(
            "mattpocock/skills"
        )
        with pytest.raises(ValueError, match=f"/vendors/0/{case['field']}"):
            write_legacy(tmp_path)
        assert_that((tmp_path / "vendors.yaml").exists()).is_false()
        assert_that((tmp_path / "bundles.yaml").exists()).is_false()
    else:
        assert_that(raw["deps"][0]["depName"]).is_equal_to("mattpocock/skills")
    assert_that((path.read_bytes(), path.stat().st_mode)).is_equal_to(snapshot)
    desired = load_unique_yaml_text(
        text=scalar_source(case, '"', indent=indent, reverse=reverse)
    )
    sources = [
        scalar_source(case, quote, indent=indent, reverse=reverse)
        for quote in ("'", '"')
    ]
    sources.extend([dump_document(desired), patch_document(text=plain, data=desired)])
    for source in sources:
        path.write_text(source)
        before = (path.read_bytes(), path.stat().st_mode)
        manifest = load_manifest(path)
        assert_that(getattr(manifest.vendors[0], case["field"])).is_equal_to(
            case["value"]
        )
        if case["publish"]:
            assert_that(write_legacy(tmp_path)).is_zero()
            assert_that(write_legacy(tmp_path, check=True)).is_zero()
        else:
            # Manifest strings remain broad; existing unsupported legacy branches
            # still fail closed, including negative/space/colon/dot spellings.
            with pytest.raises(ValueError, match="branch"):
                write_legacy(tmp_path)
            assert_that((tmp_path / "vendors.yaml").exists()).is_false()
        assert_that((path.read_bytes(), path.stat().st_mode)).is_equal_to(before)
        result = renovate_run(
            source, json.dumps([{"depIndex": 0, "newDigest": "f" * 40}])
        )
        assert_that(result["deps"]).is_length(len(manifest.vendors))
        assert_that(result["deps"][0]["currentValue"]).is_equal_to(
            manifest.vendors[0].branch
        )
        assert_that(result["deps"][0]["currentDigest"]).is_equal_to(
            manifest.vendors[0].sha
        )
        assert_that(result["updateErrors"]).is_empty()
        start, end = result["matches"][0]["spans"]["currentDigest"]
        expected = source[:start] + "f" * 40 + source[end:]
        assert_that(result["updates"]).is_equal_to([expected])
        path.write_text(expected)
        after = read_document(path)
        prior = cast(dict[str, Any], load_unique_yaml_text(text=source))
        prior["vendors"][0]["sha"] = "f" * 40
        assert_that(after).is_equal_to(prior)


@pytest.mark.parametrize("separator", ["\x85", "\u2028", "\u2029"])
def test_actual_unicode_line_folding_parity(
    tmp_path: Path,
    renovate_run: Callable[..., dict[str, Any]],
    separator: str,
) -> None:
    """Real parser line folding differences get escaped semantic-string controls."""
    path = tmp_path / "ai-skills.yaml"
    source = (
        "apiVersion: ai-skills.dev/v1\npublisher: {id: example}\nexports: []\n"
        "vendors:\n  - id: first\n    repo: owner/first\n"
        f"    sha: {'a' * 40}\n    branch: main{separator}      next\n"
    )
    data = cast(dict[str, Any], load_unique_yaml_text(text=source))
    semantic = data["vendors"][0]["branch"]
    raw = renovate_run(source)
    assert_that(raw["deps"][0]["currentValue"]).is_not_equal_to(semantic)
    path.write_text(source)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="/vendors/0/branch"):
        load_manifest(path)
    assert_that(path.read_bytes()).is_equal_to(before)
    for rendered in (dump_document(data), patch_document(text=source, data=data)):
        path.write_text(rendered)
        assert_that(load_manifest(path).vendors[0].branch).is_equal_to(semantic)
        result = renovate_run(
            rendered, json.dumps([{"depIndex": 0, "newDigest": "f" * 40}])
        )
        assert_that(result["deps"][0]["currentValue"]).is_equal_to(semantic)
        assert_that(result["updates"]).is_equal_to(
            [rendered.replace("a" * 40, "f" * 40)]
        )
        assert_that(result["updateErrors"]).is_empty()


@pytest.mark.parametrize("field", ["sha", "branch"])
@pytest.mark.parametrize("separator", ["\x85", "\u2028", "\u2029"])
@pytest.mark.parametrize("position", ["leading", "trailing"])
def test_actual_unicode_scalar_boundaries(
    tmp_path: Path,
    renovate_run: Callable[..., dict[str, Any]],
    field: str,
    separator: str,
    position: str,
) -> None:
    """A break outside PyYAML's token must also receive the quoted-string fix."""
    source = line_break_source(field=field, separator=separator, position=position)
    data = cast(dict[str, Any], load_unique_yaml_text(text=source))
    assert_that(renovate_run(source)["parsed"][0]["vendors"][0][field]).is_not_equal_to(
        data["vendors"][0][field]
    )
    path = tmp_path / "ai-skills.yaml"
    path.write_text(source)
    path.chmod(0o640)
    before = (path.read_bytes(), path.stat().st_mode)
    with pytest.raises(ValueError, match=f"/vendors/0/{field}"):
        load_manifest(path)
    assert_that((path.read_bytes(), path.stat().st_mode)).is_equal_to(before)
    for rendered in (dump_document(data), patch_document(text=source, data=data)):
        path.write_text(rendered)
        assert_that(read_document(path)).is_equal_to(data)
        result = renovate_run(
            rendered, json.dumps([{"depIndex": 0, "newDigest": "f" * 40}])
        )
        assert_that(result["deps"]).is_length(2)
        start, end = result["matches"][0]["spans"]["currentDigest"]
        assert_that(result["updates"]).is_equal_to(
            [rendered[:start] + "f" * 40 + rendered[end:]]
        )
        assert_that((path.read_bytes(), path.stat().st_mode)).is_equal_to(
            (rendered.encode(), before[1])
        )
