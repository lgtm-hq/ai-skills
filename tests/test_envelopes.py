"""Host envelopes come only from the artifact index, filtered, for every host."""

from __future__ import annotations

import copy
import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from artifact_helpers import bake_fixture, index_at
from assertpy import assert_that

from ai_skills_engine import cli, envelopes
from ai_skills_engine.bake import vendor_plugins
from ai_skills_engine.envelopes import (
    ALL_HOSTS,
    EnvelopeError,
    Host,
    Layout,
    Marketplace,
    PackageEnvelope,
    SliceSource,
    generate,
)
from ai_skills_engine.generate import marketplace
from ai_skills_engine.generate.envelope_catalog import catalog_packages
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.registry.plugin_manifest import (
    plugin_manifest_bytes,
    vendor_envelope,
    write_plugin_manifests,
)
from ai_skills_engine.registry.vendor import Vendor
from ai_skills_engine.registry.vendor_plugin import VendorPlugin

pytest_plugins = ["artifact_helpers"]

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures/envelopes"
INDEX = FIXTURE / "index.json"
GOLDEN = FIXTURE / "golden"
CREW = "fixture/crew:specialist/reviewer"
BETA = "fixture/core:skill/beta"
GAMMA = "fixture/extras:skill/gamma"
GOLDEN_ARGUMENTS = {
    "built-unfiltered": [],
    "built-filtered": ["--exclude", GAMMA],
    "slice-unfiltered": ["--layout", "slice", "--exclude", CREW],
    "slice-filtered": ["--layout", "slice", "--exclude", CREW, "--exclude", BETA],
}


def _tree(root: Path) -> dict[str, bytes]:
    """Read every regular file below a directory.

    Args:
        root: Directory to read.

    Returns:
        POSIX relative path to bytes.
    """
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _index() -> dict[str, Any]:
    """Load the committed fixture index.

    Returns:
        Parsed artifact index.
    """
    return dict(json.loads(INDEX.read_text(encoding="utf-8")))


@pytest.fixture
def envelope_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy the synthetic publication and prohibit network use.

    Args:
        tmp_path: Isolated directory.
        monkeypatch: Offline network guard.

    Returns:
        Fixture publication root.
    """

    def forbidden(*_args: object, **_kwargs: object) -> None:
        """Reject network acquisition in envelope tests."""
        pytest.fail("Envelope tests must remain offline")

    monkeypatch.setattr("socket.socket.connect", forbidden)
    root = tmp_path / "author"
    shutil.copytree(src=FIXTURE / "source", dst=root)
    return root


def _unexport_crew(root: Path) -> None:
    """Remove the specialist package, which has no in-repo slice projection.

    Args:
        root: Fixture publication root.
    """
    document = read_document(root / "ai-skills.yaml")
    document["exports"] = ["core", "extras"]
    (root / "ai-skills.yaml").write_text(dump_document(document))


def _built(*, keep: frozenset[str] | None) -> dict[str, bytes]:
    """Generate the fixture's built envelope tree.

    Args:
        keep: Kept capability IDs.

    Returns:
        Relative path to bytes.
    """
    return generate(
        _index(),
        keep,
        ALL_HOSTS,
        marketplace=Marketplace(
            name="ai-skills",
            owner="fixture",
            description="d",
            version="2.0.0",
            notice="n",
            layout=Layout.BUILT,
            plugin_root="plugins/",
        ),
        packages=catalog_packages(
            root=FIXTURE / "source", include_vendors=True, slices=False
        ),
    )


def test_fixture_index_is_the_real_builder_output(
    envelope_repo: Path, tmp_path: Path
) -> None:
    """The golden input is the actual #573 builder's index for the source."""
    output = tmp_path / "artifacts"
    bake_fixture(root=envelope_repo, destination=output)
    assert_that((output / "index.json").read_bytes()).is_equal_to(INDEX.read_bytes())


@pytest.mark.parametrize("name", sorted(GOLDEN_ARGUMENTS))
def test_golden_envelopes(name: str, envelope_repo: Path, tmp_path: Path) -> None:
    """The public command reproduces every committed golden tree byte for byte."""
    output = tmp_path / name
    arguments = [
        "--repo-root",
        str(envelope_repo),
        "generate",
        "--index",
        str(INDEX),
        "--output",
        str(output),
        *GOLDEN_ARGUMENTS[name],
    ]
    assert_that(cli.main(arguments)).is_zero()
    expected = _tree(GOLDEN / name)
    assert_that(_tree(output)).is_equal_to(expected)
    hosts = {".claude-plugin", ".cursor-plugin", ".agents"}
    assert_that({path.split("/", 1)[0] for path in expected}).contains(*hosts)


def test_goldens_cover_every_host_filtered_and_unfiltered() -> None:
    """Claude, Cursor and Codex plugin and marketplace goldens are present."""
    built = _tree(GOLDEN / "built-unfiltered")
    for plugin in ("core", "extras", "crew"):
        assert_that(built).contains_key(
            f"plugins/{plugin}/plugin.json",
            f"plugins/{plugin}/.claude-plugin/plugin.json",
            f"plugins/{plugin}/.cursor-plugin/plugin.json",
            f"plugins/{plugin}/.codex-plugin/plugin.json",
        )
    codex = json.loads(built["plugins/core/.codex-plugin/plugin.json"])
    assert_that(list(codex)).is_equal_to(["name", "version", "description", "author"])
    cursor = json.loads(built["plugins/core/.cursor-plugin/plugin.json"])
    assert_that(cursor).contains_entry({"displayName": "Core Workflow"})
    assert_that(cursor).contains_entry({"skills": "./skills/"})
    assert_that(cursor).does_not_contain_key("license")
    filtered = _tree(GOLDEN / "built-filtered")
    assert_that(filtered).does_not_contain_key("plugins/extras/plugin.json")
    assert_that(
        json.loads(_tree(GOLDEN / "slice-filtered")[".claude-plugin/marketplace.json"])[
            "plugins"
        ][0]["skills"]
    ).is_equal_to(["./skills/alpha"])


def _without(value: Any, *, needle: str) -> Any:
    """Remove list entries that reference a removed plugin or slice.

    Args:
        value: Parsed JSON.
        needle: Plugin name or slice path that must disappear.

    Returns:
        Copy without matching list items.
    """
    if isinstance(value, dict):
        return {key: _without(item, needle=needle) for key, item in value.items()}
    if isinstance(value, list):
        return [
            _without(item, needle=needle)
            for item in value
            if item != needle
            and not (isinstance(item, dict) and item.get("name") == needle)
        ]
    return value


@pytest.mark.parametrize(
    ("excluded", "needle", "layout"),
    [
        (BETA, "./skills/beta", Layout.SLICE),
        (GAMMA, "extras", Layout.SLICE),
        (GAMMA, "extras", Layout.BUILT),
        (CREW, "crew", Layout.BUILT),
    ],
)
def test_excluding_one_capability_removes_only_it(
    excluded: str, needle: str, layout: Layout
) -> None:
    """Every envelope and marketplace drops exactly that capability or package."""
    index = _index()
    every = frozenset(
        capability["id"]
        for package in index["packages"]
        for capability in package["capabilities"]
    )
    base = every - {CREW} if layout is Layout.SLICE else every
    identity = Marketplace(
        name="ai-skills",
        owner="fixture",
        description="d",
        version="2.0.0",
        notice="n",
        layout=layout,
        plugin_root="plugins/",
    )
    packages = catalog_packages(
        root=FIXTURE / "source",
        include_vendors=False,
        slices=layout is Layout.SLICE,
    )
    before = generate(index, base, ALL_HOSTS, marketplace=identity, packages=packages)
    after = generate(
        index, base - {excluded}, ALL_HOSTS, marketplace=identity, packages=packages
    )
    removed_directory = f"plugins/{needle}/"
    assert_that(
        {path for path in before if not path.startswith(removed_directory)}
    ).is_equal_to(set(after))
    for path, data in after.items():
        assert_that(json.loads(data)).described_as(path).is_equal_to(
            _without(json.loads(before[path]), needle=needle)
        )
        assert_that(data.decode()).does_not_contain(f'"{needle}"')
    changed = [path for path in after if after[path] != before[path]]
    assert_that(changed).is_not_empty()


def test_unsupported_role_fails_with_capability_id(
    envelope_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A workflow has no envelope projection yet, so generation names it."""
    (envelope_repo / "commands").mkdir()
    (envelope_repo / "commands" / "ship.md").write_text(
        "---\ndescription: Fixture workflow.\n---\n\n# Ship\n\nShip it.\n"
    )
    document = read_document(envelope_repo / "ai-skills.yaml")
    document["packages"][0]["capabilities"].append(
        {"id": "ship", "path": "commands/ship.md", "role": "workflow"}
    )
    (envelope_repo / "ai-skills.yaml").write_text(dump_document(document))
    output = tmp_path / "artifacts"
    bake_fixture(root=envelope_repo, destination=output)
    index = index_at(output)
    with pytest.raises(EnvelopeError, match="fixture/core:workflow/ship.*workflow"):
        generate(
            index,
            None,
            {Host.CODEX},
            marketplace=Marketplace(
                name="m",
                owner="o",
                description="d",
                version="2.0.0",
                notice="n",
                layout=Layout.BUILT,
            ),
            packages=catalog_packages(
                root=envelope_repo, include_vendors=True, slices=False
            ),
        )
    arguments = ["generate", "--repo-root", str(envelope_repo)]
    assert_that(cli.main([*arguments, "--output", str(tmp_path / "e")])).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains(
        "fixture/core:workflow/ship", "no claude envelope projection"
    )
    assert_that((tmp_path / "e").exists()).is_false()
    excluded = ["--exclude", "fixture/core:workflow/ship"]
    assert_that(
        cli.main([*arguments, "--output", str(tmp_path / "e"), *excluded])
    ).is_zero()


def test_first_party_slice_must_match_artifact_tree(
    envelope_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A slice whose bytes differ from the artifact tree needs a built envelope."""
    _unexport_crew(envelope_repo)
    arguments = ["--repo-root", str(envelope_repo), "generate"]
    assert_that(cli.main(arguments)).is_zero()
    assert_that(cli.main([*arguments, "--check", "--index", str(INDEX)])).is_zero()
    skill = envelope_repo / "skills" / "alpha" / "SKILL.md"
    skill.write_text(skill.read_text() + "\nChanged after the artifact build.\n")
    assert_that(cli.main([*arguments, "--check", "--index", str(INDEX)])).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains(
        "fixture/core:skill/alpha",
        "in-repo slice skills/alpha differs from the artifact tree",
        "package fixture/core needs a built envelope",
    )


def test_specialist_has_no_slice_projection(
    envelope_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Repo-root slices list skills only; a specialist package needs a build."""
    assert_that(
        cli.main(["--repo-root", str(envelope_repo), "generate", "--check"])
    ).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains(
        CREW, "package fixture/crew needs a built envelope"
    )


def test_artifact_only_resources_require_a_built_envelope() -> None:
    """Capabilities with index-declared ``_shared`` copies are never sliced."""
    golden = json.loads(
        (Path(__file__).parent / "fixtures/artifacts/golden/index.json").read_text()
    )
    record = golden["packages"][0]
    sliced = {
        item["id"]: SliceSource(
            path=f"skills/{item['id'].rsplit('/', 1)[1]}",
            tree_digest=item["treeDigest"],
        )
        for item in record["capabilities"]
    }
    package = PackageEnvelope(
        package=record["id"],
        plugin="tools",
        display_name="Tools",
        description="d",
        plugin_description="d",
        author="fixture",
        slices=sliced,
    )
    identity = Marketplace(
        name="m",
        owner="o",
        description="d",
        version="1.2.3",
        notice="n",
        layout=Layout.SLICE,
    )
    with pytest.raises(EnvelopeError, match="artifact-only resources"):
        generate(golden, None, ALL_HOSTS, marketplace=identity, packages=[package])
    with pytest.raises(EnvelopeError, match="requires excluded capability"):
        generate(
            golden,
            frozenset({"fixture/tools:skill/start"}),
            ALL_HOSTS,
            marketplace=identity,
            packages=[package],
        )


def test_generation_errors_are_explicit() -> None:
    """Unknown keeps, absent packages and colliding plugin names fail closed."""
    identity = Marketplace(
        name="m",
        owner="o",
        description="d",
        version="2.0.0",
        notice="n",
        layout=Layout.BUILT,
    )
    packages = catalog_packages(
        root=FIXTURE / "source", include_vendors=True, slices=False
    )
    with pytest.raises(EnvelopeError, match="not in the artifact: fixture/x"):
        generate(
            _index(),
            frozenset({"fixture/x:skill/y"}),
            ALL_HOSTS,
            marketplace=identity,
            packages=packages,
        )
    absent = PackageEnvelope(
        package="fixture/absent",
        plugin="absent",
        display_name="a",
        description="d",
        plugin_description="d",
        author="a",
    )
    with pytest.raises(EnvelopeError, match="fixture/absent is not in the artifact"):
        generate(_index(), None, ALL_HOSTS, marketplace=identity, packages=[absent])
    duplicate = [packages[0], packages[0]]
    with pytest.raises(EnvelopeError, match="Duplicate plugin name: core"):
        generate(_index(), None, ALL_HOSTS, marketplace=identity, packages=duplicate)
    invalid = copy.deepcopy(_index())
    invalid["artifactFormat"] = 2
    with pytest.raises(ValueError, match="Invalid artifact index"):
        generate(invalid, None, ALL_HOSTS, marketplace=identity, packages=packages)


def test_host_selection_limits_outputs() -> None:
    """Requested hosts receive envelopes; the neutral plugin.json always ships."""
    files = generate(
        _index(),
        None,
        {Host.CODEX},
        marketplace=Marketplace(
            name="ai-skills",
            owner="fixture",
            description="d",
            version="2.0.0",
            notice="n",
            layout=Layout.BUILT,
            plugin_root="plugins/",
        ),
        packages=catalog_packages(
            root=FIXTURE / "source", include_vendors=True, slices=False
        ),
    )
    assert_that(
        sorted(path for path in files if path.startswith("plugins/core/"))
    ).is_equal_to(
        ["plugins/core/.codex-plugin/plugin.json", "plugins/core/plugin.json"]
    )
    assert_that(files).contains_key(".agents/plugins/marketplace.json")
    assert_that(files).does_not_contain_key(".claude-plugin/marketplace.json")
    built = _tree(GOLDEN / "built-unfiltered")
    for path, data in files.items():
        if path.startswith("plugins/"):
            assert_that(data).described_as(path).is_equal_to(built[path])


def test_codex_rules_keep_the_minimal_unverified_payload() -> None:
    """Codex fields follow the M5 evidence; unproven fields are not invented."""
    rules = envelopes.rules()
    codex = rules["hosts"]["codex"]
    assert_that(codex["plugin"]["fields"]).is_equal_to(
        ["name", "version", "description", "author"]
    )
    assert_that(codex["evidence"]["state"]).is_equal_to("unverified")
    assert_that(codex["marketplace"]["path"]).is_equal_to(
        ".agents/plugins/marketplace.json"
    )
    for host in rules["hosts"].values():
        assert_that(set(host["roles"])).is_equal_to({"skill", "specialist"})
        for role in host["roles"].values():
            assert_that((ROOT / role["evidence"]).is_file()).is_true()
    shipped = (ROOT / "src/ai_skills_engine/data/envelope-rules.v1.json").read_bytes()
    assert_that(shipped).is_equal_to(
        (ROOT / "schemas/envelope-rules.v1.json").read_bytes()
    )


def test_corrupt_rules_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rule vocabulary drift is an error, never a silently skipped field."""
    original = copy.deepcopy(envelopes.rules())
    changed = copy.deepcopy(original)
    changed["hosts"]["codex"]["plugin"]["fields"].append("interface")
    monkeypatch.setattr(envelopes, "rules", lambda: changed)
    with pytest.raises(EnvelopeError, match="Unknown plugin envelope field: interface"):
        _built(keep=None)
    changed["hosts"]["codex"]["plugin"]["fields"].pop()
    changed["hosts"]["codex"]["marketplace"]["entries"]["built"].append("category")
    with pytest.raises(
        EnvelopeError, match="Unknown marketplace entry field: category"
    ):
        _built(keep=None)
    changed["hosts"]["codex"]["marketplace"]["entries"]["built"].pop()
    changed["hosts"]["codex"]["marketplace"]["fields"].append("interface")
    with pytest.raises(EnvelopeError, match="Unknown marketplace field: interface"):
        _built(keep=None)
    monkeypatch.undo()


def test_unsupported_rule_versions_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The generator refuses rule documents it does not implement."""
    (tmp_path / envelopes.RULES_NAME).write_text('{"rulesVersion": 2}')
    monkeypatch.setattr(
        envelopes, "resources", SimpleNamespace(files=lambda _package: tmp_path)
    )
    envelopes.rules.cache_clear()
    try:
        with pytest.raises(EnvelopeError, match="Unsupported envelope rules"):
            envelopes.rules()
    finally:
        envelopes.rules.cache_clear()


def _vendor() -> tuple[Vendor, VendorPlugin]:
    """Return a registry vendor and plugin for the bake delegation checks.

    Returns:
        Vendor and plugin slice.
    """
    plugin = VendorPlugin(
        id="core",
        description="Everyday workflow skills.",
        skills_root="skills",
        skills="*",
        agents=("reviewer",),
    )
    vendor = Vendor(
        id="fixture",
        repo="fixture-org/envelopes",
        sha="0" * 40,
        skill_roots=("skills",),
        license="MIT",
        homepage="https://example.invalid/fixture",
        plugins=(plugin,),
    )
    return vendor, plugin


def test_vendor_bake_delegates_to_the_envelope_generator(tmp_path: Path) -> None:
    """Baked per-plugin envelopes equal generate()'s built-layout bytes."""
    vendor, plugin = _vendor()
    presentation = vendor_envelope(plugin=plugin, vendor=vendor)
    files = generate(
        _index(),
        None,
        ALL_HOSTS,
        marketplace=Marketplace(
            name="m",
            owner="o",
            description="d",
            version="2.0.0",
            notice="n",
            layout=Layout.BUILT,
        ),
        packages=[replace(presentation, package="fixture/core")],
    )
    baked = plugin_manifest_bytes(plugin=plugin, vendor=vendor, version="2.0.0")
    assert_that({f"core/{path}": data for path, data in baked.items()}).is_equal_to(
        {path: data for path, data in files.items() if path.startswith("core/")}
    )
    assert_that(json.loads(baked[".cursor-plugin/plugin.json"])).contains_entry(
        {"license": "MIT"}
    )
    write_plugin_manifests(
        destination=tmp_path, plugin=plugin, vendor=vendor, version="2.0.0"
    )
    vendor_plugins._assert_host_manifests(
        plugin_dir=tmp_path, plugin=plugin, vendor=vendor, version="2.0.0"
    )
    (tmp_path / ".codex-plugin" / "plugin.json").write_text("{}\n")
    with pytest.raises(ValueError, match="Generated file is stale: .*codex-plugin"):
        vendor_plugins._assert_host_manifests(
            plugin_dir=tmp_path, plugin=plugin, vendor=vendor, version="2.0.0"
        )
    (tmp_path / ".codex-plugin" / "plugin.json").unlink()
    with pytest.raises(ValueError, match="Missing generated file: .*codex-plugin"):
        vendor_plugins._assert_host_manifests(
            plugin_dir=tmp_path, plugin=plugin, vendor=vendor, version="2.0.0"
        )


def test_envelope_writes_reject_symlinks(tmp_path: Path) -> None:
    """Neither direct writes nor built output follow a symlinked path."""
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "link").symlink_to(target)
    with pytest.raises(EnvelopeError, match="Symlink rejected"):
        envelopes.write_files(destination=tmp_path / "link", files={"a.json": b"{}"})
    assert_that(list(target.iterdir())).is_empty()
    arguments = [
        "generate",
        "--repo-root",
        str(FIXTURE / "source"),
        "--index",
        str(INDEX),
        "--output",
        str(tmp_path / "link" / "out"),
    ]
    assert_that(cli.main(arguments)).is_equal_to(1)
    assert_that(list(target.iterdir())).is_empty()


def test_cli_routes_and_argument_errors(
    envelope_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bare generate writes/checks; named targets and misuse keep their routes."""
    _unexport_crew(envelope_repo)
    root = f"--repo-root={envelope_repo}"
    assert_that(cli.main([root, "generate"])).is_zero()
    assert_that(cli.main([root, "generate", "--check"])).is_zero()
    assert_that(cli.main([root, "generate", "marketplace", "--check"])).is_zero()
    assert_that(
        marketplace.main(["--check", "--repo-root", str(envelope_repo)])
    ).is_zero()
    with pytest.raises(SystemExit) as error:
        cli.main([root, "generate", "--exclude", BETA])
    assert_that(error.value.code).is_equal_to(2)
    assert_that(capsys.readouterr().err).contains("require --output")
    assert_that(
        cli.main(
            [
                root,
                "generate",
                "--output",
                str(envelope_repo / "o"),
                "--exclude",
                "x/y:skill/z",
            ]
        )
    ).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("not in the artifact: x/y:skill/z")
    built = envelope_repo / "built"
    assert_that(
        cli.main([root, "generate", "--output", str(built), "--host", "cursor"])
    ).is_zero()
    assert_that(_tree(built)).contains_key(
        ".cursor-plugin/marketplace.json", "plugins/core/.cursor-plugin/plugin.json"
    )
    assert_that(_tree(built)).does_not_contain_key(".claude-plugin/marketplace.json")


def test_vendor_presentation_comes_from_the_manifest(envelope_repo: Path) -> None:
    """Exported mapped vendor packages keep the bake's presentation rules."""
    document = read_document(envelope_repo / "ai-skills.yaml")
    document["vendors"] = [
        {
            "id": "acme",
            "repo": "acme-org/skills",
            "sha": "1" * 40,
            "license": "Apache-2.0",
            "homepage": "https://github.com/acme-org/skills",
            "mapping": {
                "skillRoots": ["skills"],
                "packages": [
                    {
                        "id": "tools",
                        "description": "Acme tools.",
                        "skillsRoot": "skills",
                        "skills": "*",
                    }
                ],
            },
        }
    ]
    document["exports"] = [*document["exports"], "acme/tools"]
    (envelope_repo / "ai-skills.yaml").write_text(dump_document(document))
    vendor = catalog_packages(root=envelope_repo, include_vendors=True, slices=False)[
        -1
    ]
    assert_that(vendor).is_equal_to(
        PackageEnvelope(
            package="acme/tools",
            plugin="tools",
            display_name="tools",
            description="Acme tools.",
            plugin_description="Acme tools. [baked from vendor 'acme']",
            author="acme-org",
            license="Apache-2.0",
        )
    )
    assert_that(
        catalog_packages(root=envelope_repo, include_vendors=False, slices=False)
    ).is_length(3)
    arguments = ["generate", "--repo-root", str(envelope_repo), "--index", str(INDEX)]
    assert_that(
        cli.main([*arguments, "--output", str(envelope_repo / "out")])
    ).is_equal_to(1)


def test_supplied_index_must_be_a_valid_object(
    envelope_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A malformed --index fails before any write."""
    bad = tmp_path / "index.json"
    bad.write_text("[]\n")
    arguments = ["generate", "--repo-root", str(envelope_repo), "--index", str(bad)]
    assert_that(cli.main([*arguments, "--check"])).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("Artifact index must be an object")
    assert_that(marketplace.marketplace_output_path(repo_root=tmp_path)).is_equal_to(
        tmp_path / ".claude-plugin/marketplace.json"
    )
    assert_that(
        marketplace.cursor_marketplace_output_path(repo_root=tmp_path)
    ).is_equal_to(tmp_path / ".cursor-plugin/marketplace.json")
