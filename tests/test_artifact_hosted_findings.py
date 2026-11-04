"""Exercise hosted path findings through inventory and public artifact builds."""

import copy
import json
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.artifacts.format import canonical_tar, validate_index
from ai_skills_engine.artifacts.materialize import materialize
from ai_skills_engine.provenance.input_files import input_files
from ai_skills_engine.selection.load import load_inputs

pytest_plugins = ["inventory_helpers"]


@pytest.mark.parametrize("file_capability", [False, True], ids=["directory", "file"])
@pytest.mark.parametrize(
    "reference,portable",
    [
        ("../../", False),
        ("../../../", False),
        ("../", False),
        ("./?view=tree#top", True),
        ("./", True),
        ("assets/", True),
        ("assets/?view=tree#image", True),
        ("assets/image.svg?raw=1#image", True),
        ("absent/", False),
    ],
)
def test_directory_references_at_inventory_and_build_boundaries(
    tmp_path: Path, file_capability: bool, reference: str, portable: bool
) -> None:
    """Flattened ancestors diagnose; emitted directories and files stay portable."""
    source = tmp_path / "skills/deep/start"
    (source / "assets").mkdir(parents=True)
    (source / "assets/image.svg").write_text("<svg/>\n")
    name = "entry.md" if file_capability else "SKILL.md"
    (source / name).write_text(
        "---\nname: start\ndescription: Fixture.\n---\n"
        f"[link]({reference})\n[defined][target]\n\n[target]: {reference}\n"
        "\n`[literal](missing/)`\n"
    )
    if not file_capability:
        (source / "notes").mkdir()
        (source / "notes/guide.md").write_text("[Root](../?view=tree#top)\n")
    declaration = {
        "id": "start",
        "role": "instruction" if file_capability else "skill",
        "path": f"skills/deep/start/{name}" if file_capability else "skills/deep/start",
    }
    document = {
        "apiVersion": "ai-skills.dev/v1",
        "publisher": {"id": "fixture", "repo": "fixture/catalog"},
        "packages": [{"id": "tools", "capabilities": [declaration]}],
        "exports": ["tools"],
    }
    (tmp_path / "ai-skills.yaml").write_text(json.dumps(document))
    inventory, selection = load_inputs(tmp_path)
    assert_that(inventory.capabilities).is_length(1)
    capability = inventory.capabilities[0]
    arguments: dict[str, Any] = {
        "capability": capability,
        "source": source / name if file_capability else source,
        "resources": (),
    }
    files, _resources, losses = materialize(**arguments)
    # A file capability does not include sibling assets; its own parent is meaningful.
    expected = portable and (not file_capability or reference.startswith("./"))
    assert_that(bool(losses)).is_equal_to(not expected)
    if losses:
        assert_that({item["mode"] for item in losses}).is_equal_to(
            {"user-explode", "repo-materialize"}
        )
        assert_that({item["state"] for item in losses}).is_equal_to(
            {"source-unportable"}
        )
    assert_that(materialize(**arguments)[0]).is_equal_to(files)
    assert_that(files[name][0]).contains(
        b"?view=tree#" if "view=" in reference else b"[link]"
    )
    args = ["--repo-root", str(tmp_path), "build"]
    assert_that(cli.main([*args, "--write-digests"])).is_equal_to(
        int(not selection.valid)
    )
    if not selection.valid:
        assert_that((tmp_path / "dist/artifacts/index.json").exists()).is_false()
        return
    before = {p.name: p.read_bytes() for p in (tmp_path / "dist/artifacts").iterdir()}
    assert_that(cli.main([*args, "--check"])).is_zero()
    assert_that(
        {p.name: p.read_bytes() for p in (tmp_path / "dist/artifacts").iterdir()}
    ).is_equal_to(before)
    index = json.loads((tmp_path / "dist/artifacts/index.json").read_text())
    assert_that(index["packages"][0]["capabilities"][0]["portability"]).is_equal_to(
        losses
    )


@pytest.mark.parametrize("field", ["capability", "copy", "resource", "legal", "notice"])
@pytest.mark.parametrize(
    "separator",
    [chr(code) for code in range(1, 32)] + ["\r\n", "\x7f", "\x85", "\u2028", "\u2029"],
)
def test_complete_index_paths_reject_hidden_traversal(
    field: str, separator: str
) -> None:
    """Every complete-index path pattern rejects traversal across control spellings."""
    golden = json.loads(
        (Path(__file__).parent / "fixtures/artifacts/golden/index.json").read_text()
    )
    validate_index(golden)
    document = copy.deepcopy(golden)
    targets = {
        "capability": document["packages"][0]["capabilities"][0],
        "copy": document["packages"][0]["capabilities"][0]["resources"][0],
        "resource": document["packages"][0]["resources"][0],
        "legal": document["legalFiles"][0],
        "notice": document["packages"][0]["capabilities"][0],
    }
    target = targets[field]
    key = "notices" if field == "notice" else "path"
    # These bytes are legal POSIX filename bytes; traversal alone is forbidden.
    ordinary = f"dir{separator}/ordinary/file.txt"
    target[key] = [ordinary] if field == "notice" else ordinary
    validate_index(document)
    for path in (
        f"dir{separator}/../../escape",
        f"dir{separator}/..",
        "../escape",
        "/escape",
        "dir\\escape",
        "dir\0escape",
    ):
        target[key] = [path] if field == "notice" else path
        with pytest.raises(ValueError, match="Invalid artifact index"):
            validate_index(document)
        with pytest.raises(ValueError, match="Unsafe artifact entry"):
            canonical_tar({path: (b"payload", 0o644)})


@pytest.mark.parametrize(
    "target,accepted",
    [
        ("file.txt", True),
        ("directory/../file.txt", True),
        ("directory/../directory/../file.txt", True),
        ("missing/../file.txt", False),
        ("file.txt/../file.txt", False),
        ("link/../file.txt", False),
        ("directory-link/../file.txt", False),
        ("chain/../file.txt", False),
        ("../../vendor/navigation/file.txt", False),
    ],
)
def test_alias_components_at_input_and_pinned_public_build_boundaries(
    inventory_repo: tuple[Path, Path], target: str, accepted: bool
) -> None:
    """Aliases preserve all path bytes/modes and reject erased unsafe components."""
    root, vendor = inventory_repo
    # Only this subtree contains navigation aliases, outside observed payloads.
    navigation = vendor / "navigation"
    navigation.mkdir()
    (navigation / "directory").mkdir()
    (navigation / "file.txt").write_bytes(b"Unselected navigation target.\n")
    (navigation / "file.txt").chmod(0o640)
    if "link" in target or "chain" in target:
        (navigation / "link").symlink_to("file.txt")
    if target.startswith("directory-link"):
        (navigation / "directory-link").symlink_to("directory")
    if target.startswith("chain"):
        (navigation / "chain").symlink_to("link")
    alias = navigation / "alias"
    alias.symlink_to(target)
    before = _snapshot(vendor)
    if accepted:
        observed = input_files(root=vendor, protected=(PurePosixPath("skills"),))
        assert_that([str(item.path) for item in observed]).contains(
            "navigation/file.txt"
        )
        assert_that(alias.exists()).is_true()
    else:
        with pytest.raises(ValueError):
            input_files(root=vendor, protected=(PurePosixPath("skills"),))
    document = yaml.safe_load((root / "ai-skills.yaml").read_text())
    document["policy"] = {"provenance": {"mode": "strict"}}
    (root / "ai-skills.yaml").write_text(json.dumps(document))
    result = cli.main(
        [
            "--repo-root",
            str(root),
            "build",
            "--vendor-tree",
            f"vendor={vendor}",
            "--write-digests",
        ]
    )
    assert_that(result).is_equal_to(0 if accepted else 1)
    assert_that(_snapshot(vendor)).is_equal_to(before)
    assert_that(alias.readlink().as_posix()).is_equal_to(target)


def _snapshot(root: Path) -> dict[str, tuple[bytes | str | None, int]]:
    """Observe links lexically and regular bytes/modes without following aliases.

    Args:
        root: Read-only fixture pin.

    Returns:
        Every relative node, its bytes or link spelling, and its original mode.
    """
    return {
        p.relative_to(root).as_posix(): (
            (
                p.readlink().as_posix()
                if p.is_symlink()
                else p.read_bytes() if p.is_file() else None
            ),
            p.lstat().st_mode,
        )
        for p in (root, *root.rglob("*"))
    }


@pytest.mark.parametrize(
    "reference,file_capability",
    [
        ("../../", False),
        ("_shared/fixture/shared/", False),
        ("absent/", False),
        ("./", True),
    ],
)
def test_resource_directories_cannot_mask_unmapped_source_targets(
    tmp_path: Path, reference: str, file_capability: bool
) -> None:
    """Mismatched source paths and ambiguously relocated file parents diagnose."""
    source = tmp_path / ("shared" if file_capability else "skills/start")
    source.mkdir(parents=True)
    name = "entry.md" if file_capability else "SKILL.md"
    (source / name).write_text(
        "---\nname: start\ndescription: Fixture.\n---\n" + f"[link]({reference})\n"
    )
    (tmp_path / "shared").mkdir(exist_ok=True)
    (tmp_path / "shared/image.svg").write_text("<svg/>\n")
    document = {
        "apiVersion": "ai-skills.dev/v1",
        "publisher": {"id": "fixture", "repo": "fixture/catalog"},
        "packages": [
            {
                "id": "tools",
                "capabilities": [
                    {
                        "id": "start",
                        "role": "instruction" if file_capability else "skill",
                        "path": (
                            "shared/entry.md" if file_capability else "skills/start"
                        ),
                    }
                ],
                "artifactResources": {
                    "version": 1,
                    "resources": [{"id": "image", "path": "shared/image.svg"}],
                    "bindings": {
                        ("instruction/start" if file_capability else "skill/start"): [
                            "image"
                        ]
                    },
                },
            }
        ],
        "exports": ["tools"],
    }
    (tmp_path / "ai-skills.yaml").write_text(json.dumps(document))
    inventory, _selection = load_inputs(tmp_path)
    files, _copies, losses = materialize(
        capability=inventory.capabilities[0],
        source=source / name if file_capability else source,
        resources=((inventory.resources[0], tmp_path / "shared/image.svg"),),
    )
    assert_that(files).contains_key("_shared/fixture/shared/image.svg")
    assert_that({item["state"] for item in losses}).is_equal_to({"source-unportable"})
