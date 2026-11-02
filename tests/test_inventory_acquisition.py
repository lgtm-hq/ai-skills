"""Real materialization must reject unsafe fetched bytes without pruning them."""

import shutil
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.bake import vendor_plugins
from ai_skills_engine.inventory import load_inventory
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.registry.vendor import Vendor

pytest_plugins = ["inventory_helpers"]


@pytest.fixture
def fetched_fixture(
    inventory_repo: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, list[Path]]:
    """Stub only network acquisition, preserving links, modes and real validation."""
    root, snapshot = inventory_repo
    destinations: list[Path] = []

    def fetch(*, vendor: Vendor, dest: Path) -> None:
        """Supply exactly the pinned fixture without executing its scripts."""
        assert_that((vendor.repo, vendor.sha)).is_equal_to(
            ("upstream/tools", "0123456789abcdef0123456789abcdef01234567")
        )
        shutil.copytree(src=snapshot, dst=dest, symlinks=True)
        destinations.append(dest)

    monkeypatch.setattr(vendor_plugins, "_fetch_vendor_tree", fetch)
    return root, snapshot, destinations


def _manifest_vendor(root: Path, vendor: Path) -> None:
    """Declare vendor-owned payload and resource paths, removing mapping authority."""
    path = root / "ai-skills.yaml"
    document = read_document(path)
    document["vendors"][0].pop("mapping")
    document["exports"] = ["tools", "upstream/tools"]
    document["packages"][0]["capabilities"][0]["requires"] = [
        "upstream/tools:skill/helper"
    ]
    path.write_text(dump_document(document))
    (vendor / "ai-skills.yaml").write_text(
        dump_document(
            {
                "apiVersion": "ai-skills.dev/v1",
                "publisher": {"id": "upstream"},
                "packages": [
                    {
                        "id": "tools",
                        "capabilities": [
                            {
                                "id": "helper",
                                "path": "skills/help",
                                "resources": ["upstream/tools:resource/notice"],
                            }
                        ],
                        "resources": [{"id": "notice", "path": "NOTICE.md"}],
                    }
                ],
            }
        )
    )


@pytest.mark.parametrize("manifest", [False, True], ids=["mapped", "manifest"])
def test_pristine_fetch_matches_offline_payloads_and_modes(
    fetched_fixture: tuple[Path, Path, list[Path]], manifest: bool
) -> None:
    """Safe inputs have identical hashes, modes, resources and declared edges."""
    root, vendor, _ = fetched_fixture
    if manifest:
        _manifest_vendor(root, vendor)
    (vendor / "skills/help/danger.py").chmod(0o751)
    offline = load_inventory(root, vendor_roots={"vendor": vendor})
    fetched = load_inventory(root, fetch_vendors=True)
    assert_that(fetched.capabilities).is_equal_to(offline.capabilities)
    assert_that(fetched.resources).is_equal_to(offline.resources)
    assert_that([item for item in fetched.diagnostics if not item.warning]).is_empty()
    helper = next(item for item in fetched.capabilities if item.id.name == "helper")
    assert_that(
        next(item.mode for item in helper.payload if str(item.path) == "danger.py")
    ).is_equal_to(0o751)
    assert_that(list(vendor.rglob("MUST-NOT-EXECUTE"))).is_empty()


@pytest.mark.parametrize(
    "manifest,unsafe",
    [
        (True, "skills/help/link.md"),
        (True, "NOTICE.md"),
        (True, "skills"),
        (False, "skills/help/link.md"),
        (False, "agents/reviewer.md"),
        (False, "extras/bonus/link.md"),
        (False, "NOTICE.md"),
        (False, "skills"),
    ],
)
def test_real_fetch_rejects_unsafe_declared_bytes_without_deleting_links(
    fetched_fixture: tuple[Path, Path, list[Path]],
    capsys: pytest.CaptureFixture[str],
    manifest: bool,
    unsafe: str,
) -> None:
    """Acquisition cannot turn an unsafe offline payload into a clean inventory."""
    root, vendor, destinations = fetched_fixture
    if manifest:
        _manifest_vendor(root, vendor)
    else:
        document = read_document(root / "ai-skills.yaml")
        package = document["vendors"][0]["mapping"]["packages"][0]
        package["extraSkills"] = ["extras/bonus"]
        (vendor / "extras/bonus").mkdir(parents=True)
        (vendor / "extras/bonus/SKILL.md").write_text(
            "---\nname: bonus\ndescription: Extra.\n---\n"
        )
        # Only the package root declares skills; a global root must not mask bugs.
        document["vendors"][0]["mapping"]["skillRoots"] = []
        (root / "ai-skills.yaml").write_text(dump_document(document))
    link = vendor / unsafe
    if link.exists():
        if link.is_dir():
            link.rename(vendor / "real-skills")
        else:
            link.unlink()
    link.symlink_to("/missing-inventory-target")
    offline = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that(
        [item for item in offline.diagnostics if not item.warning]
    ).is_not_empty()

    with pytest.raises(ValueError, match="symlink rejected"):
        load_inventory(root, fetch_vendors=True)
    assert_that(destinations).is_length(1)
    assert_that(link.is_symlink()).is_true()
    assert_that(
        cli.main(["inventory", "--repo-root", str(root), "--fetch-vendors", "--json"])
    ).is_equal_to(1)
    output = capsys.readouterr()
    assert_that(output.err).contains("symlink rejected")
    assert_that(output.out).is_empty()


def test_documentation_alias_preserves_legacy_bake_and_fails_pristine_inventory(
    fetched_fixture: tuple[Path, Path, list[Path]], tmp_path: Path
) -> None:
    """Unrelated aliases remain a legacy bake exception, never inventory pruning."""
    root, vendor, _ = fetched_fixture
    (vendor / "AGENTS.md").symlink_to("NOTICE.md")
    offline = load_inventory(root, vendor_roots={"vendor": vendor})
    assert_that([item for item in offline.diagnostics if not item.warning]).is_empty()
    with pytest.raises(ValueError, match="symlink rejected"):
        load_inventory(root, fetch_vendors=True)
    materialized = vendor_plugins._materialize_vendor_tree(
        vendor=Vendor(
            id="vendor",
            repo="upstream/tools",
            sha="0123456789abcdef0123456789abcdef01234567",
            skill_roots=("skills",),
            license="",
            homepage="",
        ),
        trees={},
        temporary_root=tmp_path / "legacy",
    )
    assert_that((materialized / "AGENTS.md").is_symlink()).is_false()
    assert_that((vendor / "AGENTS.md").is_symlink()).is_true()
