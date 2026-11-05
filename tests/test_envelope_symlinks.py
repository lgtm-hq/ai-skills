"""Envelope writers reject symlinks they write through, not the caller's ancestors.

macOS ships ``/var -> /private/var`` (so the default temporary directory has a
symlinked ancestor) and some Linux layouts symlink ``$TMPDIR`` or ``/home``.
Generation, the drift gate and the vendor bake must work there, while a
symlink inside a writer's destination tree is still refused.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from artifact_helpers import bake_fixture
from assertpy import assert_that

from ai_skills_engine import cli, envelopes
from ai_skills_engine.bake import vendor_plugins as baker
from ai_skills_engine.envelopes import EnvelopeError
from ai_skills_engine.generate import marketplace
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.registry.plugin_bake import bake_vendor_plugins
from ai_skills_engine.registry.plugin_manifest import write_plugin_manifests
from ai_skills_engine.registry.registry import load_registry
from ai_skills_engine.registry.vendor import Vendor

pytest_plugins = ["artifact_helpers", "ingest_helpers"]

FIXTURE = Path(__file__).parent / "fixtures/envelopes"
INDEX = FIXTURE / "index.json"


@pytest.fixture
def linked_tmpdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the process temporary directory at a symlink to a real directory.

    Args:
        tmp_path: Isolated directory.
        monkeypatch: Restores the temporary directory afterwards.

    Returns:
        The real directory behind the symlinked temporary directory.
    """
    real = tmp_path / "real-tmp"
    real.mkdir()
    link = tmp_path / "link-tmp"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(tempfile, "tempdir", str(link))
    assert_that(tempfile.gettempdir()).is_equal_to(str(link))
    return real


@pytest.fixture
def publication(tmp_path: Path) -> Path:
    """Copy the synthetic publication with only slice-representable exports.

    Args:
        tmp_path: Isolated directory.

    Returns:
        Publication root.
    """
    root = tmp_path / "author"
    shutil.copytree(src=FIXTURE / "source", dst=root)
    document = read_document(root / "ai-skills.yaml")
    document["exports"] = ["core", "extras"]
    (root / "ai-skills.yaml").write_text(dump_document(document))
    return root


def test_generate_and_check_through_a_symlinked_tmpdir(
    publication: Path, linked_tmpdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The offline publisher index stages in a resolved temporary directory."""
    arguments = ["--repo-root", str(publication), "generate"]
    assert_that(cli.main(arguments)).described_as(capsys.readouterr().err).is_zero()
    assert_that(cli.main([*arguments, "--check"])).is_zero()
    assert_that(
        marketplace.main(["--check", "--repo-root", str(publication)])
    ).is_zero()
    output = Path(tempfile.gettempdir()) / "built"
    assert_that(cli.main([*arguments, "--output", str(output)])).is_zero()
    assert_that(str(capsys.readouterr().err)).is_empty()
    assert_that((linked_tmpdir / "built/plugins/core/plugin.json").is_file()).is_true()
    assert_that(sorted(path.name for path in linked_tmpdir.iterdir())).is_equal_to(
        ["built"]
    )


def test_generate_and_check_through_a_symlinked_repo_root(
    publication: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ``--repo-root`` override behind a symlink is resolved, not rejected."""
    link = tmp_path / "checkout"
    link.symlink_to(publication, target_is_directory=True)
    arguments = ["--repo-root", str(link), "generate"]
    assert_that(cli.main(arguments)).described_as(capsys.readouterr().err).is_zero()
    assert_that((publication / ".agents/plugins/marketplace.json").is_file()).is_true()
    assert_that(cli.main([*arguments, "--check"])).is_zero()
    assert_that(marketplace.main(["--check", "--repo-root", str(link)])).is_zero()
    assert_that(
        cli.main([*arguments, "--index", str(INDEX), "--output", str(link / "o")])
    ).is_zero()
    assert_that((publication / "o/.claude-plugin/marketplace.json").is_file()).is_true()


def test_vendor_bake_through_a_symlinked_tmpdir(
    ingest_repo: tuple[Path, Path, Vendor], linked_tmpdir: Path
) -> None:
    """Direct and full vendor bakes stage envelopes below a symlinked TMPDIR."""
    root, source, vendor = ingest_repo
    direct = root / "direct"
    bake_vendor_plugins(vendor=vendor, vendor_root=source, output_root=direct)
    assert_that(
        (direct / "synthetic-plugin/.codex-plugin/plugin.json").is_file()
    ).is_true()
    baker.bake(repo_root=root, vendor_trees={vendor.id: source})
    assert_that(baker.check(repo_root=root)).is_zero()
    assert_that(list(linked_tmpdir.iterdir())).is_empty()


@pytest.mark.parametrize(
    "linked",
    [".codex-plugin", ".codex-plugin/plugin.json", "plugin.json"],
    ids=["intermediate", "leaf", "top-level-leaf"],
)
def test_symlinks_inside_the_destination_are_still_rejected(
    tmp_path: Path, linked: str
) -> None:
    """Writers refuse a symlinked leaf or intermediate below their destination."""
    destination = tmp_path / "plugin"
    destination.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "target"
    if linked.endswith(".json"):
        target.write_text("outside\n")
    else:
        target.mkdir()
    link = destination / linked
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    files = {"plugin.json": b"{}\n", ".codex-plugin/plugin.json": b"{}\n"}
    with pytest.raises(EnvelopeError, match="Symlink rejected in envelope path"):
        envelopes.write_files(destination=destination, files=files)
    vendor = load_registry(registry_path=Path(__file__).parents[1] / "vendors.yaml")[0]
    with pytest.raises(EnvelopeError, match="Symlink rejected in envelope path"):
        write_plugin_manifests(
            destination=destination,
            plugin=vendor.plugins[0],
            vendor=vendor,
            version="1.0.0",
        )
    if target.is_dir():
        assert_that(list(target.iterdir())).is_empty()
    else:
        assert_that(target.read_text()).is_equal_to("outside\n")


def test_symlinked_destination_and_escaping_paths_are_rejected(
    tmp_path: Path,
) -> None:
    """The destination itself and relative paths escaping it stay refused."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(EnvelopeError, match="Symlink rejected in envelope path"):
        envelopes.write_files(destination=link, files={"a.json": b"{}\n"})
    with pytest.raises(EnvelopeError, match="escapes"):
        envelopes.write_files(destination=real, files={"../a.json": b"{}\n"})
    assert_that(list(real.iterdir())).is_empty()
    assert_that((tmp_path / "a.json").exists()).is_false()
    arguments = [
        "generate",
        "--repo-root",
        str(FIXTURE / "source"),
        "--index",
        str(INDEX),
        "--output",
        str(link),
    ]
    assert_that(cli.main(arguments)).is_equal_to(1)
    assert_that(list(real.iterdir())).is_empty()
    allowed = [*arguments[:-1], str(link / "out")]
    assert_that(cli.main(allowed)).is_zero()
    assert_that((real / "out/plugins/core/plugin.json").is_file()).is_true()


def test_artifact_writer_keeps_its_destination_symlink_guard(
    publication: Path, tmp_path: Path
) -> None:
    """Control: ``write_artifacts`` still refuses a symlinked output path."""
    real = tmp_path / "real-artifacts"
    real.mkdir()
    link = tmp_path / "link-artifacts"
    link.symlink_to(real, target_is_directory=True)
    for destination in (link, link / "nested"):
        with pytest.raises(ValueError, match="Symlink rejected in artifact output"):
            bake_fixture(root=publication, destination=destination)
    assert_that(list(real.iterdir())).is_empty()
