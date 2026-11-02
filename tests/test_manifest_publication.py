"""Legacy publication fails closed when it cannot honor manifest declarations."""

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.legacy import (
    legacy_documents,
    render_legacy,
    write_legacy,
)
from ai_skills_engine.manifest.load import read_document

pytest_plugins = ("manifest_helpers",)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "change",
    [
        "baseline",
        "disjoint",
        "extension-extension",
        "extension-default",
        "default-extension",
        "ungrouped",
    ],
)
def test_legacy_rejects_duplicate_effective_destinations_before_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: str
) -> None:
    """Schema-valid package identities cannot overwrite a shared legacy destination."""
    data = read_document(ROOT / "ai-skills.yaml")
    first = data["packages"][0]
    if change != "baseline":
        source = data["packages"][-1] if change == "ungrouped" else first
        duplicate = copy.deepcopy(source)
        duplicate["id"] = "duplicate-copy"
        duplicate["capabilities"] = [{"id": "distinct", "path": "skills/distinct"}]
        duplicate["x-useful-note"] = {"preserve": True}
        if change == "disjoint":
            duplicate["x-legacy-group"] = "distinct-group"
        elif change == "extension-default":
            first["x-legacy-group"] = duplicate["id"]
            duplicate.pop("x-legacy-group")
        elif change == "default-extension":
            first.pop("x-legacy-group")
            duplicate["x-legacy-group"] = first["id"]
        data["packages"].append(duplicate)
        if change != "ungrouped":
            data["exports"].append(duplicate["id"])
    path = tmp_path / "ai-skills.yaml"
    path.write_text(dump_document(data))
    args = ["--repo-root", str(tmp_path), "manifest"]
    assert_that(cli.main([*args, "validate"])).is_zero()
    before = {}
    for name in ("bundles.yaml", "vendors.yaml"):
        before[name] = b"# preexisting sentinel: " + name.encode() + b"\n"
        (tmp_path / name).write_bytes(before[name])
    manifest_before = path.read_bytes()
    if change in {"baseline", "disjoint"}:
        rendered = render_legacy(tmp_path)
        assert_that(write_legacy(tmp_path, check=True)).is_equal_to(1)
        for name, content in before.items():
            assert_that((tmp_path / name).read_bytes()).is_equal_to(content)
        assert_that(cli.main([*args, "legacy"])).is_zero()
        assert_that(cli.main([*args, "legacy", "--check"])).is_zero()
        for destination, content in rendered.items():
            assert_that(destination.read_bytes()).is_equal_to(content)
        groups = read_document(tmp_path / "bundles.yaml")["groups"]
        assert_that(groups).is_length(8 if change == "disjoint" else 7)
        if change == "disjoint":
            assert_that(groups["distinct-group"]["skills"]).is_equal_to(["distinct"])
        else:
            for name in before:
                assert_that((tmp_path / name).read_bytes()).is_equal_to(
                    (ROOT / name).read_bytes()
                )
    else:
        for operation in (
            lambda: legacy_documents(data),
            lambda: render_legacy(tmp_path),
            lambda: write_legacy(tmp_path),
            lambda: write_legacy(tmp_path, check=True),
        ):
            with pytest.raises(ValueError, match="Legacy.*duplicate.*destination"):
                operation()
        for check in (["--check"], [], ["--check"]):
            assert_that(cli.main([*args, "legacy", *check])).is_equal_to(1)
            assert_that(capsys.readouterr().out).contains(
                "Legacy", "duplicate", "destination", "duplicate-copy"
            )
            for name, content in before.items():
                assert_that((tmp_path / name).read_bytes()).is_equal_to(content)
    assert_that(path.read_bytes()).is_equal_to(manifest_before)


@pytest.mark.parametrize(
    ("owner", "declaration"),
    [
        (owner, declaration)
        for owner in ("local", "vendor")
        for declaration in (
            "baseline",
            "requires",
            "resources",
            "package-resources",
            "empty",
            "related",
        )
        if owner == "local" or declaration != "package-resources"
    ],
)
def test_legacy_cli_rejects_unrepresentable_dependencies_before_writes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    owner: str,
    declaration: str,
) -> None:
    """Schema-valid dependencies cannot disappear through legacy publication."""
    data = read_document(ROOT / "ai-skills.yaml")
    if owner == "vendor":
        vendor = next(item for item in data["vendors"] if item["id"] == "anthropics")
        package = vendor["mapping"]["packages"][0]
        package["skills"] = ["docx"]
        qualified = f"anthropics/{package['id']}"
        capability: dict[str, Any] = {}
        package["capabilities"] = {"docx": capability}
    else:
        package = data["packages"][0]
        qualified = f"lgtm-hq/{package['id']}"
        capability = package["capabilities"][0]
    if declaration == "requires":
        capability["requires"] = ["anthropics/document-skills:skill/pdf"]
    elif declaration == "resources":
        capability["resources"] = [f"{qualified}:resource/guide"]
    elif declaration == "package-resources":
        package["resources"] = [{"id": "guide", "path": "shared/guide.md"}]
    elif declaration == "empty":
        capability.update(requires=[], resources=[], related=[])
        if owner == "local":
            package["resources"] = []
    elif declaration == "related":
        capability["related"] = ["anthropics/document-skills:skill/pdf"]
    path = tmp_path / "ai-skills.yaml"
    path.write_text(dump_document(data))
    args = ["--repo-root", str(tmp_path), "manifest"]
    # Establish actual schema and semantic validity before testing publication.
    assert_that(cli.main([*args, "validate"])).is_zero()
    expected = 1 if declaration in {"requires", "resources", "package-resources"} else 0
    before = {}
    for name in ("bundles.yaml", "vendors.yaml"):
        before[name] = b"# preexisting sentinel: " + name.encode() + b"\n"
        (tmp_path / name).write_bytes(before[name])
    manifest_before = path.read_bytes()
    if expected:
        with pytest.raises(ValueError, match="Legacy.*cannot represent"):
            render_legacy(tmp_path)
        for check in (["--check"], [], ["--check"]):
            assert_that(cli.main([*args, "legacy", *check])).is_equal_to(1)
            assert_that(capsys.readouterr().out).contains(
                "Legacy",
                "cannot represent",
                qualified,
                declaration.removeprefix("package-"),
            )
            for name, content in before.items():
                assert_that((tmp_path / name).read_bytes()).is_equal_to(content)
    else:
        rendered = render_legacy(tmp_path)
        assert_that(cli.main([*args, "legacy", "--check"])).is_equal_to(1)
        for name, content in before.items():
            assert_that((tmp_path / name).read_bytes()).is_equal_to(content)
        assert_that(cli.main([*args, "legacy"])).is_zero()
        assert_that(cli.main([*args, "legacy", "--check"])).is_zero()
        for destination, content in rendered.items():
            assert_that(destination.read_bytes()).is_equal_to(content)
        if owner == "local":
            for name in before:
                assert_that((tmp_path / name).read_bytes()).is_equal_to(
                    (ROOT / name).read_bytes()
                )
        else:
            published = read_document(tmp_path / "vendors.yaml")["vendors"]
            mapped = next(item for item in published if item["id"] == "anthropics")
            assert_that(mapped["plugins"][0]["skills"]).is_equal_to(["docx"])
            assert_that(mapped["plugins"][0]).does_not_contain_key("capabilities")
    assert_that(path.read_bytes()).is_equal_to(manifest_before)


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
