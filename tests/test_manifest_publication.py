"""Legacy publication fails closed when it cannot honor manifest declarations."""

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.generate.marketplace import _load_bundles
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.layout import encode_template
from ai_skills_engine.manifest.legacy import (
    legacy_documents,
    render_legacy,
    write_legacy,
)
from ai_skills_engine.manifest.load import load_manifest, read_document
from ai_skills_engine.registry.registry import load_registry

pytest_plugins = ("manifest_helpers",)
pytestmark = pytest.mark.usefixtures("author_skills")

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "change",
    [
        "baseline",
        "optional-fields",
        "license",
        "homepage",
        "mapping-description",
        "local-name",
        "empty-roots",
        "invalid-homepage",
        "invalid-branch",
        "empty-mapping-description",
        "no-vendors",
        "bad-group-key",
    ],
)
def test_compatibility_publication_checks_real_readers_before_either_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: str
) -> None:
    """Valid engine declarations must also satisfy both compatibility readers."""
    data = read_document(ROOT / "ai-skills.yaml")
    vendor = data["vendors"][0]
    package = vendor["mapping"]["packages"][0]
    if change in {"license", "homepage"}:
        vendor.pop(change)
    elif change == "mapping-description":
        package.pop("description")
    elif change == "local-name":
        data["packages"][0].pop("name")
    elif change == "empty-roots":
        vendor["mapping"]["skillRoots"] = []
    elif change == "invalid-homepage":
        vendor["homepage"] = "not-a-url"
    elif change == "invalid-branch":
        vendor["branch"] = "bad..branch"
    elif change == "empty-mapping-description":
        package["description"] = ""
    elif change == "no-vendors":
        data["vendors"] = []
        data["exports"] = [value for value in data["exports"] if "/" not in value]
    elif change == "bad-group-key":
        data["packages"][0]["x-legacy-group"] = "Invalid key"
    elif change == "optional-fields":
        vendor.pop("branch", None)
        vendor.pop("displayRef", None)
        data["packages"][0].pop("description")
    path = tmp_path / "ai-skills.yaml"
    path.write_text(dump_document(data))
    load_manifest(path)
    before = {}
    for name in ("bundles.yaml", "vendors.yaml"):
        before[name] = b"# unchanged sentinel " + name.encode() + b"\n"
        (tmp_path / name).write_bytes(before[name])
    manifest_before = path.read_bytes()
    args = ["--repo-root", str(tmp_path), "manifest", "legacy"]
    if change in {"baseline", "optional-fields"}:
        rendered = render_legacy(tmp_path)
        assert_that(write_legacy(tmp_path, check=True)).is_equal_to(1)
        for name, content in before.items():
            assert_that((tmp_path / name).read_bytes()).is_equal_to(content)
        assert_that(cli.main(args)).is_zero()
        assert_that(cli.main([*args, "--check"])).is_zero()
        assert_that(
            load_registry(registry_path=tmp_path / "vendors.yaml")
        ).is_not_empty()
        assert_that(_load_bundles(repo_root=tmp_path).groups).is_not_empty()
        for destination, content in rendered.items():
            assert_that(destination.read_bytes()).is_equal_to(content)
        if change == "baseline":
            for name in before:
                assert_that((tmp_path / name).read_bytes()).is_equal_to(
                    (ROOT / name).read_bytes()
                )
    else:
        for operation in (
            lambda: render_legacy(tmp_path),
            lambda: write_legacy(tmp_path),
            lambda: write_legacy(tmp_path, check=True),
        ):
            with pytest.raises(ValueError, match="Legacy publication.*reader"):
                operation()
            for name, content in before.items():
                assert_that((tmp_path / name).read_bytes()).is_equal_to(content)
        for check in ([], ["--check"]):
            assert_that(cli.main([*args, *check])).is_equal_to(1)
            assert_that(capsys.readouterr().out).contains(
                "Legacy publication", "reader"
            )
            for name, content in before.items():
                assert_that((tmp_path / name).read_bytes()).is_equal_to(content)
    assert_that(path.read_bytes()).is_equal_to(manifest_before)


def test_legacy_cli_patches_shape_inside_stored_flow_template(tmp_path: Path) -> None:
    """The real renderer and CLI can extend a mapping nested in a flow sequence."""
    data = read_document(ROOT / "ai-skills.yaml")
    document = legacy_documents(data)["vendors.yaml"]
    # A compact flow template is valid input; retain it as the formatting authority.
    template = "# retained template\n" + yaml.safe_dump(
        document, default_flow_style=True, sort_keys=False
    )
    data["x-legacy-format"]["vendors.yaml"] = encode_template(template.encode())
    data["vendors"][0]["mapping"]["packages"][0]["extraFiles"] = ["NOTICE.md", "😀.txt"]
    (tmp_path / "ai-skills.yaml").write_text(dump_document(data))
    rendered = render_legacy(tmp_path)
    assert_that(write_legacy(tmp_path)).is_zero()
    args = ["--repo-root", str(tmp_path), "manifest", "legacy"]
    assert_that(cli.main(args)).is_zero()
    assert_that(cli.main([*args, "--check"])).is_zero()
    for destination, content in rendered.items():
        assert_that(destination.read_bytes()).is_equal_to(content)
    assert_that((tmp_path / "vendors.yaml").read_text()).contains(
        "# retained template\n"
    )
    assert_that(
        load_registry(registry_path=tmp_path / "vendors.yaml")[0].plugins[0].extra_files
    ).is_equal_to(("NOTICE.md", "😀.txt"))


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
            duplicate["x-legacy-group"] = duplicate["id"]
            payload = tmp_path / "skills/distinct"
            payload.mkdir()
            (payload / "SKILL.md").write_text(
                "---\nname: distinct\ndescription: Distinct fixture skill.\n---\n"
                "\nA declared local publication fixture.\n"
            )
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
            assert_that(groups["duplicate-copy"]["skills"]).is_equal_to(["distinct"])
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
    before = {
        path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()
    }
    args = ["--repo-root", str(tmp_path), "manifest"]
    assert_that(cli.main([*args, "validate"])).is_zero()
    expected = 0 if change in {"baseline", "qualified", "include-all"} else 1
    for check in ([], ["--check"]):
        assert_that(cli.main([*args, "legacy", *check])).is_equal_to(expected)
        if expected:
            assert_that(capsys.readouterr().out).contains("Legacy", "cannot represent")
        assert_that(
            {
                path.name: path.read_bytes()
                for path in tmp_path.iterdir()
                if path.is_file()
            }
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
        package["capabilities"] = [{"id": "new-skill", "path": "skills/new-skill"}]
        data["packages"].append(package)
        data["exports"].append("new-package")
    elif change == "skill":
        data["packages"][0]["capabilities"].append(
            {"id": "new-skill", "path": "skills/new-skill"}
        )
    else:
        vendor = copy.deepcopy(data["vendors"][0])
        vendor.update(id="new-vendor", repo="example/new-vendor")
        vendor["mapping"]["packages"][0]["id"] = "new-vendor-skills"
        data["vendors"].append(vendor)
        data["exports"].extend(
            f"new-vendor/{package['id']}" for package in vendor["mapping"]["packages"]
        )
    if change in {"package", "skill"}:
        payload = tmp_path / "skills/new-skill"
        payload.mkdir()
        (payload / "SKILL.md").write_text(
            "---\nname: new-skill\ndescription: New fixture skill.\n---\n"
            "\nA declared local publication fixture.\n"
        )
    (tmp_path / "ai-skills.yaml").write_text(dump_document(data))
    args = ["--repo-root", str(tmp_path), "manifest"]
    assert_that(cli.main([*args, "legacy"])).is_zero()
    before = {
        path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()
    }
    for name in ("ai-skills.yaml", "bundles.yaml", "vendors.yaml"):
        check_yaml(tmp_path / name)
    assert_that(cli.main([*args, "legacy"])).is_zero()
    assert_that(cli.main([*args, "legacy", "--check"])).is_zero()
    assert_that(
        {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    ).is_equal_to(before)
