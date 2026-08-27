"""Tests for ``scripts/generate_marketplace.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from assertpy import assert_that


def _load_generate_marketplace_module() -> ModuleType:
    """Load ``generate_marketplace`` from the scripts directory (not a package).

    Returns:
        The loaded module object.

    Raises:
        RuntimeError: If the module spec or loader cannot be constructed.
    """
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "generate_marketplace.py"
    spec = importlib.util.spec_from_file_location(
        name="generate_marketplace",
        location=path,
    )
    if spec is None:
        msg = f"Could not load module spec from {path}"
        raise RuntimeError(msg)
    loader = spec.loader
    if loader is None:
        msg = f"Module spec for {path} has no loader"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def _write_skill(*, repo_root: Path, skill_id: str) -> None:
    """Create a minimal skill directory for tests.

    Args:
        repo_root: Fake repository root.
        skill_id: Skill directory name under ``skills/``.
    """
    skill_dir = repo_root / "skills" / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(
        f"---\nname: {skill_id}\ndescription: Test skill.\n---\n",
        encoding="utf-8",
    )


def _write_bundles(*, repo_root: Path, body: str) -> None:
    """Write ``bundles.yaml`` in a fake repository root.

    Args:
        repo_root: Fake repository root.
        body: YAML file contents.
    """
    repo_root.joinpath("bundles.yaml").write_text(body, encoding="utf-8")


def _write_version(*, repo_root: Path, version: str) -> None:
    """Write a root ``VERSION`` file.

    Args:
        repo_root: Fake repository root.
        version: Version string to stamp.
    """
    repo_root.joinpath("VERSION").write_text(f"{version}\n", encoding="utf-8")


def _write_pyproject(*, repo_root: Path, version: str) -> None:
    """Write a minimal ``pyproject.toml`` with ``project.version``.

    Args:
        repo_root: Fake repository root.
        version: Version string to stamp.
    """
    repo_root.joinpath("pyproject.toml").write_text(
        f'[project]\nname = "fake"\nversion = "{version}"\n',
        encoding="utf-8",
    )


def _core_bundles_yaml() -> str:
    """Return a two-skill catalog with one grouped plugin.

    Returns:
        YAML document text.
    """
    return """
groups:
  core:
    id: core
    name: Core Workflow
    description: Everyday workflow skills.
    skills:
      - alpha
ungrouped:
  - beta
"""


def test_generate_marketplace_builds_plugin_groups(tmp_path: Path) -> None:
    """Grouped skills become kebab-id plugins with sliced ./skills/<id> paths."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_skill(repo_root=tmp_path, skill_id="beta")
    _write_bundles(repo_root=tmp_path, body=_core_bundles_yaml())
    _write_pyproject(repo_root=tmp_path, version="1.2.3")

    rendered = mod.generate_marketplace(repo_root=tmp_path)
    manifest = json.loads(rendered)

    assert_that(manifest).is_equal_to(
        {
            "$generated": mod.GENERATED_NOTICE,
            "plugins": [
                {
                    "name": "core",
                    "displayName": "Core Workflow",
                    "description": "Everyday workflow skills.",
                    "version": "1.2.3",
                    "source": "./",
                    "strict": False,
                    "skills": ["./skills/alpha"],
                },
            ],
        },
    )


def test_generate_cursor_marketplace_mirrors_groups(tmp_path: Path) -> None:
    """Cursor adapter lists the same plugin ids with name/owner/metadata."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_skill(repo_root=tmp_path, skill_id="beta")
    _write_bundles(repo_root=tmp_path, body=_core_bundles_yaml())
    _write_pyproject(repo_root=tmp_path, version="1.2.3")

    manifest = json.loads(mod.generate_cursor_marketplace(repo_root=tmp_path))

    assert_that(manifest["name"]).is_equal_to("ai-skills")
    assert_that(manifest["owner"]).is_equal_to({"name": "lgtm-hq"})
    assert_that(manifest["metadata"]["version"]).is_equal_to("1.2.3")
    assert_that(manifest["metadata"]["$generated"]).is_equal_to(mod.GENERATED_NOTICE)
    assert_that(manifest["plugins"]).is_equal_to(
        [
            {
                "name": "core",
                "source": "./",
                "description": "Everyday workflow skills.",
            },
        ],
    )
    assert_that(manifest).does_not_contain_key("$generated")


def test_generate_marketplace_stamps_version_from_pyproject(tmp_path: Path) -> None:
    """Without VERSION, plugin version comes from pyproject.toml."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_skill(repo_root=tmp_path, skill_id="beta")
    _write_bundles(repo_root=tmp_path, body=_core_bundles_yaml())
    _write_pyproject(repo_root=tmp_path, version="9.9.9")

    manifest = json.loads(mod.generate_marketplace(repo_root=tmp_path))

    assert_that(manifest["plugins"][0]["version"]).is_equal_to("9.9.9")


def test_generate_marketplace_stamps_version_from_version_file(tmp_path: Path) -> None:
    """A VERSION file stamps plugins when pyproject.toml is absent."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_skill(repo_root=tmp_path, skill_id="beta")
    _write_bundles(repo_root=tmp_path, body=_core_bundles_yaml())
    _write_version(repo_root=tmp_path, version="4.5.6")

    manifest = json.loads(mod.generate_marketplace(repo_root=tmp_path))

    assert_that(manifest["plugins"][0]["version"]).is_equal_to("4.5.6")


def test_generate_marketplace_rejects_version_mismatch(tmp_path: Path) -> None:
    """VERSION and pyproject.toml must agree when both are present."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_skill(repo_root=tmp_path, skill_id="beta")
    _write_bundles(repo_root=tmp_path, body=_core_bundles_yaml())
    _write_version(repo_root=tmp_path, version="4.5.6")
    _write_pyproject(repo_root=tmp_path, version="9.9.9")

    with pytest.raises(ValueError, match=r"does not match pyproject\.toml"):
        mod.generate_marketplace(repo_root=tmp_path)


def test_generate_marketplace_rejects_empty_version_file(tmp_path: Path) -> None:
    """An empty VERSION file is a hard error, not a fall-through."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_skill(repo_root=tmp_path, skill_id="beta")
    _write_bundles(repo_root=tmp_path, body=_core_bundles_yaml())
    tmp_path.joinpath("VERSION").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="VERSION file is empty"):
        mod.generate_marketplace(repo_root=tmp_path)


def test_bundle_group_requires_non_empty_kebab_plugin_id() -> None:
    """Direct construction cannot omit or empty the plugin id."""

    mod = _load_generate_marketplace_module()
    with pytest.raises(TypeError):
        mod.BundleGroup(name="Core", skills=("alpha",))
    with pytest.raises(ValueError, match="plugin_id"):
        mod.BundleGroup(
            name="Core",
            skills=("alpha",),
            plugin_id="",
        )
    with pytest.raises(ValueError, match="plugin_id"):
        mod.BundleGroup(
            name="Core",
            skills=("alpha",),
            plugin_id="Not_Kebab",
        )


def test_generate_marketplace_rejects_missing_plugin_id(tmp_path: Path) -> None:
    """Each group must declare an explicit kebab-case id."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_pyproject(repo_root=tmp_path, version="1.0.0")
    _write_bundles(
        repo_root=tmp_path,
        body="""
groups:
  core:
    name: Core
    skills:
      - alpha
ungrouped: []
""",
    )

    with pytest.raises(TypeError, match="must have a string 'id'"):
        mod.generate_marketplace(repo_root=tmp_path)


@pytest.mark.parametrize(
    ("group_key", "plugin_id", "match"),
    [
        ("Not_Kebab", "core", "Group key"),
        ("core", "Not_Kebab", "id"),
    ],
    ids=["key", "id"],
)
def test_generate_marketplace_rejects_non_kebab_ids(
    tmp_path: Path,
    group_key: str,
    plugin_id: str,
    match: str,
) -> None:
    """Group keys and plugin ids must be kebab-case."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_pyproject(repo_root=tmp_path, version="1.0.0")
    _write_bundles(
        repo_root=tmp_path,
        body=f"""
groups:
  {group_key}:
    id: {plugin_id}
    name: Core
    skills:
      - alpha
ungrouped: []
""",
    )

    with pytest.raises(ValueError, match=match):
        mod.generate_marketplace(repo_root=tmp_path)


def test_generate_marketplace_rejects_duplicate_plugin_ids(tmp_path: Path) -> None:
    """Two groups cannot share the same plugin id."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_skill(repo_root=tmp_path, skill_id="beta")
    _write_pyproject(repo_root=tmp_path, version="1.0.0")
    _write_bundles(
        repo_root=tmp_path,
        body="""
groups:
  one:
    id: shared
    name: One
    skills:
      - alpha
  two:
    id: shared
    name: Two
    skills:
      - beta
ungrouped: []
""",
    )

    with pytest.raises(ValueError, match="Plugin id"):
        mod.generate_marketplace(repo_root=tmp_path)


def test_generate_marketplace_rejects_plugin_id_mismatch(tmp_path: Path) -> None:
    """A group's plugin id must match its YAML key so --bundle and marketplace agree."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_pyproject(repo_root=tmp_path, version="1.0.0")
    _write_bundles(
        repo_root=tmp_path,
        body="""
groups:
  core:
    id: other
    name: Core
    skills:
      - alpha
ungrouped: []
""",
    )

    with pytest.raises(ValueError, match="must match the group key"):
        mod.generate_marketplace(repo_root=tmp_path)


def _write_generated_adapters(*, repo_root: Path, mod: ModuleType) -> None:
    """Write both generated marketplace adapters for a fake repo.

    Args:
        repo_root: Fake repository root.
        mod: Loaded generate_marketplace module.
    """
    claude_path = repo_root / ".claude-plugin" / "marketplace.json"
    cursor_path = repo_root / ".cursor-plugin" / "marketplace.json"
    claude_path.parent.mkdir(parents=True, exist_ok=True)
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    claude_path.write_text(
        mod.generate_marketplace(repo_root=repo_root),
        encoding="utf-8",
    )
    cursor_path.write_text(
        mod.generate_cursor_marketplace(repo_root=repo_root),
        encoding="utf-8",
    )


def test_marketplace_drift_message_detects_stale_file(tmp_path: Path) -> None:
    """Drift check fails when a marketplace adapter does not match the generator."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_skill(repo_root=tmp_path, skill_id="beta")
    _write_bundles(repo_root=tmp_path, body=_core_bundles_yaml())
    _write_pyproject(repo_root=tmp_path, version="1.2.3")
    _write_generated_adapters(repo_root=tmp_path, mod=mod)
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(
        "{}\n",
        encoding="utf-8",
    )

    message = mod.marketplace_drift_message(repo_root=tmp_path)

    assert_that(message).is_not_none()
    assert_that(message).contains("out of date")


def test_marketplace_drift_message_passes_when_current(tmp_path: Path) -> None:
    """Drift check is silent when every marketplace adapter matches."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_skill(repo_root=tmp_path, skill_id="beta")
    _write_bundles(repo_root=tmp_path, body=_core_bundles_yaml())
    _write_pyproject(repo_root=tmp_path, version="1.2.3")
    _write_generated_adapters(repo_root=tmp_path, mod=mod)

    assert_that(mod.marketplace_drift_message(repo_root=tmp_path)).is_none()


def test_marketplace_drift_message_detects_missing_cursor_adapter(
    tmp_path: Path,
) -> None:
    """Drift check fails when the Cursor adapter has not been generated."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_skill(repo_root=tmp_path, skill_id="beta")
    _write_bundles(repo_root=tmp_path, body=_core_bundles_yaml())
    _write_pyproject(repo_root=tmp_path, version="1.2.3")
    claude_path = tmp_path / ".claude-plugin" / "marketplace.json"
    claude_path.parent.mkdir(parents=True)
    claude_path.write_text(
        mod.generate_marketplace(repo_root=tmp_path),
        encoding="utf-8",
    )

    message = mod.marketplace_drift_message(repo_root=tmp_path)

    assert_that(message).is_not_none()
    assert_that(message).contains(".cursor-plugin/marketplace.json")
    assert_that(message).contains("Missing")


def test_marketplace_drift_message_detects_missing_file(tmp_path: Path) -> None:
    """Drift check fails when marketplace.json has not been generated."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="alpha")
    _write_skill(repo_root=tmp_path, skill_id="beta")
    _write_bundles(repo_root=tmp_path, body=_core_bundles_yaml())
    _write_pyproject(repo_root=tmp_path, version="1.2.3")

    message = mod.marketplace_drift_message(repo_root=tmp_path)

    assert_that(message).is_not_none()
    assert_that(message).contains("Missing")


def test_validate_bundles_rejects_missing_skill(tmp_path: Path) -> None:
    """Every skill directory must appear in bundles.yaml."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="only-one")
    _write_pyproject(repo_root=tmp_path, version="1.0.0")
    _write_bundles(
        repo_root=tmp_path,
        body="""
groups:
  core:
    id: core
    name: Core
    skills: []
ungrouped: []
""",
    )

    with pytest.raises(ValueError, match="missing skills: only-one"):
        mod.generate_marketplace(repo_root=tmp_path)


def test_validate_bundles_rejects_duplicate_assignment(tmp_path: Path) -> None:
    """A skill cannot appear in two groups."""

    mod = _load_generate_marketplace_module()
    _write_skill(repo_root=tmp_path, skill_id="dup")
    _write_pyproject(repo_root=tmp_path, version="1.0.0")
    _write_bundles(
        repo_root=tmp_path,
        body="""
groups:
  one:
    id: one
    name: One
    skills:
      - dup
  two:
    id: two
    name: Two
    skills:
      - dup
ungrouped: []
""",
    )

    with pytest.raises(ValueError, match="listed in both"):
        mod.generate_marketplace(repo_root=tmp_path)


def test_repo_bundles_cover_all_skills() -> None:
    """Production bundles.yaml must account for every skill in skills/."""

    mod = _load_generate_marketplace_module()
    repo_root = Path(__file__).resolve().parents[1]

    # Should not raise.
    mod.generate_marketplace(repo_root=repo_root)


def test_repo_marketplace_is_current() -> None:
    """Committed host-adapter manifests must match the generator (drift gate)."""

    mod = _load_generate_marketplace_module()
    repo_root = Path(__file__).resolve().parents[1]

    assert_that(mod.marketplace_drift_message(repo_root=repo_root)).is_none()


def test_repo_plugin_ids_are_kebab_case_and_match_slicing() -> None:
    """Production plugin names are kebab-case and skills arrays match bundles."""

    mod = _load_generate_marketplace_module()
    repo_root = Path(__file__).resolve().parents[1]
    bundles = mod.load_validated_bundles(repo_root=repo_root)
    manifest = json.loads(mod.generate_marketplace(repo_root=repo_root))
    plugins = {plugin["name"]: plugin for plugin in manifest["plugins"]}

    assert_that(set(plugins)).is_equal_to(
        {group.plugin_id for group in bundles.groups.values()},
    )
    assert_that(plugins).contains_key("review")
    assert_that(plugins).contains_key("subagents")
    assert_that(plugins).does_not_contain_key("pre-push")
    assert_that(plugins).does_not_contain_key("agents")

    for group in bundles.groups.values():
        plugin = plugins[group.plugin_id]
        assert_that(plugin["name"]).matches(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
        assert_that(plugin["displayName"]).is_equal_to(group.name)
        assert_that(plugin["description"]).is_equal_to(group.description)
        assert_that(plugin["source"]).is_equal_to("./")
        assert_that(plugin["strict"]).is_false()
        assert_that(plugin["skills"]).is_equal_to(
            [f"./skills/{name}" for name in group.skills],
        )


def test_repo_cursor_marketplace_mirrors_claude_plugin_ids() -> None:
    """Cursor adapter plugin names match Claude marketplace plugin names."""

    mod = _load_generate_marketplace_module()
    repo_root = Path(__file__).resolve().parents[1]
    claude = json.loads(mod.generate_marketplace(repo_root=repo_root))
    cursor = json.loads(mod.generate_cursor_marketplace(repo_root=repo_root))
    claude_names = [plugin["name"] for plugin in claude["plugins"]]
    cursor_names = [plugin["name"] for plugin in cursor["plugins"]]

    assert_that(cursor_names).is_equal_to(claude_names)
    assert_that(cursor["name"]).is_equal_to("ai-skills")
    assert_that(cursor["owner"]["name"]).is_equal_to("lgtm-hq")
    assert_that(cursor["metadata"]["$generated"]).is_equal_to(mod.GENERATED_NOTICE)
