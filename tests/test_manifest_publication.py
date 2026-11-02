"""Legacy publication fails closed when it cannot honor manifest declarations."""

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document

pytest_plugins = ("manifest_helpers",)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "change",
    [
        "baseline",
        "qualified",
        "narrowed",
        "removed-vendor-export",
        "absent",
        "include-none",
        "include-one",
        "exclude-skill",
        "include-all",
        "export-other",
    ],
)
def test_actual_legacy_cli_publication_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: str
) -> None:
    """Real CLI preserves all-export bytes and refuses silent publication widening."""
    data = read_document(ROOT / "ai-skills.yaml")
    vendor = next(item for item in data["vendors"] if item["id"] == "anthropics")
    if change == "qualified":
        data["exports"] = [
            value if "/" in value else f"lgtm-hq/{value}" for value in data["exports"]
        ]
    elif change == "narrowed":
        data["exports"] = ["git-pr"]
        vendor["include"] = []
    elif change == "removed-vendor-export":
        data["exports"].remove("anthropics/document-skills")
    elif change == "absent":
        data.pop("exports")
    elif change == "include-none":
        vendor["include"] = []
    elif change == "include-one":
        vendor["include"] = ["anthropics/document-skills"]
    elif change == "exclude-skill":
        vendor["exclude"] = ["anthropics/document-skills:skill/pdf"]
    elif change == "include-all":
        vendor["include"] = [
            f"anthropics/{item['id']}" for item in vendor["mapping"]["packages"]
        ]
        vendor["exclude"] = []
    elif change == "export-other":
        data["exports"].append("other")
    (tmp_path / "ai-skills.yaml").write_text(dump_document(data))
    for name in ("bundles.yaml", "vendors.yaml"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    args = ["--repo-root", str(tmp_path), "manifest"]
    assert_that(cli.main([*args, "validate"])).is_zero()
    expected = 0 if change in {"baseline", "qualified", "include-all"} else 1
    for check in ([], ["--check"]):
        assert_that(cli.main([*args, "legacy", *check])).is_equal_to(expected)
        if expected:
            assert_that(capsys.readouterr().out).contains("Legacy", "cannot represent")
        assert_that(
            {path.name: path.read_bytes() for path in tmp_path.iterdir()}
        ).is_equal_to(before)


@pytest.mark.parametrize("change", ["package", "skill", "vendor"])
def test_actual_cli_collection_additions_are_lintable(
    tmp_path: Path, change: str, check_yaml: Callable[[Path], None]
) -> None:
    """Ordinary author edits render deterministic block YAML under repository rules."""
    data: dict[str, Any] = read_document(ROOT / "ai-skills.yaml")
    if change == "package":
        package = copy.deepcopy(data["packages"][0])
        package.update(id="new-package", **{"x-legacy-group": "new-package"})
        data["packages"].append(package)
        data["exports"].append("new-package")
    elif change == "skill":
        data["packages"][0]["capabilities"].append(
            {"id": "new-skill", "path": "skills/new-skill"}
        )
    else:
        vendor = copy.deepcopy(data["vendors"][0])
        vendor.update(id="new-vendor", repo="example/new-vendor")
        data["vendors"].append(vendor)
        data["exports"].extend(
            f"new-vendor/{package['id']}" for package in vendor["mapping"]["packages"]
        )
    (tmp_path / "ai-skills.yaml").write_text(dump_document(data))
    args = ["--repo-root", str(tmp_path), "manifest"]
    assert_that(cli.main([*args, "legacy"])).is_zero()
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    for name in ("ai-skills.yaml", "bundles.yaml", "vendors.yaml"):
        check_yaml(tmp_path / name)
    assert_that(cli.main([*args, "legacy"])).is_zero()
    assert_that(cli.main([*args, "legacy", "--check"])).is_zero()
    assert_that(
        {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    ).is_equal_to(before)
