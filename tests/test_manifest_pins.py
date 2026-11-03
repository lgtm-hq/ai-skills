"""Legacy management replacements remove owned fields and retain manifest metadata."""

import copy
import stat
from collections.abc import Callable
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.legacy import legacy_documents, write_legacy
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.pins import write_vendors
from ai_skills_engine.vendors import manage

pytest_plugins = ("manifest_helpers",)
pytestmark = pytest.mark.usefixtures("author_skills")

ROOT = Path(__file__).resolve().parents[1]
TRANSACTION_FILES = ("ai-skills.yaml", "bundles.yaml", "vendors.yaml")


def _snapshot(root: Path) -> dict[str, tuple[bytes, int] | None]:
    """Capture exact publication bytes, permission bits, and original absences."""
    return {
        name: (
            (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            if (path := root / name).exists()
            else None
        )
        for name in TRANSACTION_FILES
    }


@pytest.fixture
def author(tmp_path: Path) -> Path:
    """Seed real mappings plus manifest-only metadata, without fetching vendors.

    Args:
        tmp_path: Isolated repository.

    Returns:
        Manifest author root.
    """
    data = read_document(ROOT / "ai-skills.yaml")
    vendor = data["vendors"][0]
    vendor["x-vendor-note"] = "preserve"
    vendor["mapping"]["x-mapping-note"] = {"preserve": True}
    package = vendor["mapping"]["packages"][0]
    package.update(
        extraFiles=["NOTICE.md"],
        renameSkills={"teach": "teach-mapped"},
        agents=["reviewer"],
        capabilities={"teach": {"id": "stable"}},
        **{"x-package-note": "preserve"},
    )
    (tmp_path / "ai-skills.yaml").write_text(dump_document(data))
    write_legacy(tmp_path)
    return tmp_path


@pytest.fixture
def transaction_author(author: Path) -> Path:
    """Retain valid, deliberately noncanonical bytes and distinct file modes."""
    for name, mode in zip(TRANSACTION_FILES, (0o640, 0o600, 0o644), strict=True):
        path = author / name
        path.write_bytes(
            b"# original bytes\r\n" + path.read_bytes().replace(b"\n", b"\r\n")
        )
        path.chmod(mode)
    return author


@pytest.mark.parametrize("failed_name", ["bundles.yaml", "vendors.yaml"])
@pytest.mark.parametrize("partial", [False, True], ids=["untouched", "partial-write"])
@pytest.mark.parametrize("absent", [False, True], ids=["existing", "absent-originals"])
def test_real_publication_failure_restores_exact_transaction(
    transaction_author: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_name: str,
    partial: bool,
    absent: bool,
) -> None:
    """The public pin updater restores both registries after actual writer failures."""
    root = transaction_author
    vendor_id = read_document(root / "ai-skills.yaml")["vendors"][0]["id"]
    if absent:
        for name in TRANSACTION_FILES[1:]:
            (root / name).unlink()
    before = _snapshot(root)
    real_write = Path.write_bytes
    failure = PermissionError("actual registry publication failed")
    attempted: list[str] = []
    failed = False

    def publish(destination: Path, content: bytes) -> int:
        """Fail only a real destination write; allow scratch rendering and cleanup."""
        nonlocal failed
        if destination.parent == root and not failed:
            attempted.append(destination.name)
            if destination.name == failed_name:
                failed = True
                if partial:
                    real_write(destination, b"interrupted publication\n")
                    destination.chmod(0o666)
                raise failure
        return real_write(destination, content)

    monkeypatch.setattr(Path, "write_bytes", publish)
    with pytest.raises(PermissionError) as caught:
        manage.set_sha(repo_root=root, vendor_id=vendor_id, sha="f" * 40)
    assert_that(caught.value).is_same_as(failure)
    assert_that(attempted).is_equal_to(
        ["bundles.yaml"]
        if failed_name == "bundles.yaml"
        else list(TRANSACTION_FILES[1:])
    )
    assert_that(_snapshot(root)).is_equal_to(before)


@pytest.mark.parametrize("failure_stage", ["schema", "legacy-reader"])
def test_pin_validation_failure_preserves_original_bytes(
    transaction_author: Path, failure_stage: str
) -> None:
    """Actual validators reject edits without regenerating the original registries."""
    root = transaction_author
    path = root / "ai-skills.yaml"
    raw = legacy_documents(read_document(path))["vendors.yaml"]["vendors"]
    raw[0]["sha" if failure_stage == "schema" else "homepage"] = "invalid"
    before = _snapshot(root)
    with pytest.raises(ValueError, match="schema|Legacy publication.*reader"):
        write_vendors(path=path, vendors=raw)
    assert_that(_snapshot(root)).is_equal_to(before)


def test_partial_manifest_write_is_rolled_back(
    transaction_author: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Roll back a manifest write that truncates the file before raising."""
    root = transaction_author
    path = root / "ai-skills.yaml"
    raw = legacy_documents(read_document(path))["vendors.yaml"]["vendors"]
    raw[0]["sha"] = "f" * 40
    before = _snapshot(root)
    real_write = Path.write_text
    failure = OSError("interrupted manifest write")

    def interrupt(destination: Path, text: str, *, encoding: str) -> int:
        """Truncate the manifest and alter its mode before reporting the I/O error."""
        if destination == path:
            real_write(destination, text[:20], encoding=encoding)
            destination.chmod(0o666)
            raise failure
        return real_write(destination, text, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", interrupt)
    with pytest.raises(OSError) as caught:
        write_vendors(path=path, vendors=raw)
    assert_that(caught.value).is_same_as(failure)
    assert_that(_snapshot(root)).is_equal_to(before)


@pytest.mark.parametrize("cleanup", ["manifest", "registry", "absent-registry"])
@pytest.mark.parametrize("via_cli", [False, True], ids=["api", "management-cli"])
def test_cleanup_failure_preserves_publication_error_and_restores_other_files(
    transaction_author: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cleanup: str,
    via_cli: bool,
) -> None:
    """Identify cleanup failures without masking the original publication error."""
    root = transaction_author
    path = root / "ai-skills.yaml"
    raw = legacy_documents(read_document(path))["vendors.yaml"]["vendors"]
    raw[0]["sha"] = "f" * 40
    if cleanup == "absent-registry":
        (root / "bundles.yaml").unlink()
    before = _snapshot(root)
    blocked = path if cleanup == "manifest" else root / "bundles.yaml"
    real_write, real_unlink = Path.write_bytes, Path.unlink
    failure = PermissionError("original publication error")
    failed = False

    def publish(destination: Path, content: bytes) -> int:
        """Reach the second publication, then fail one independent cleanup step."""
        nonlocal failed
        if destination == root / "vendors.yaml" and not failed:
            failed = True
            real_write(destination, b"partial registry\n")
            raise failure
        if failed and destination == blocked:
            raise PermissionError("cleanup write denied")
        return real_write(destination, content)

    def unlink(destination: Path, missing_ok: bool = False) -> None:
        """Deny removal of a registry that had no original file."""
        if destination == blocked:
            raise PermissionError("cleanup unlink denied")
        real_unlink(destination, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "write_bytes", publish)
    if cleanup == "absent-registry":
        monkeypatch.setattr(Path, "unlink", unlink)
    if via_cli:
        assert_that(
            manage.main(
                [
                    "update",
                    "--repo-root",
                    str(root),
                    "--id",
                    raw[0]["id"],
                    "--sha",
                    raw[0]["sha"],
                ]
            )
        ).is_equal_to(1)
        assert_that(capsys.readouterr().err).contains(
            str(failure), str(blocked), "cleanup", "before retrying"
        )
    else:
        with pytest.raises(PermissionError) as caught:
            write_vendors(path=path, vendors=raw)
        assert_that(caught.value).is_same_as(failure)
        assert_that("\n".join(caught.value.__notes__)).contains(str(blocked), "cleanup")
    after = _snapshot(root)
    assert_that(after[blocked.name]).is_not_equal_to(before[blocked.name])
    for name in before:
        if name != blocked.name:
            assert_that(after[name]).described_as(name).is_equal_to(before[name])


def test_pin_noop_does_not_write_authoritative_or_published_files(
    author: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep a current pin's exact bytes without opening destinations for write."""
    path = author / "ai-skills.yaml"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    vendor = read_document(path)["vendors"][0]
    before = _snapshot(author)
    real_text, real_bytes = Path.write_text, Path.write_bytes
    writes: list[Path] = []

    def text_write(destination: Path, text: str, *, encoding: str) -> int:
        """Observe author writes while allowing the actual publication renderer."""
        if destination.parent == author:
            writes.append(destination)
        return real_text(destination, text, encoding=encoding)

    def bytes_write(destination: Path, content: bytes) -> int:
        """Observe destination bytes separately from scratch reader inputs."""
        if destination.parent == author:
            writes.append(destination)
        return real_bytes(destination, content)

    monkeypatch.setattr(Path, "write_text", text_write)
    monkeypatch.setattr(Path, "write_bytes", bytes_write)
    manage.set_sha(repo_root=author, vendor_id=vendor["id"], sha=vendor["sha"])
    assert_that(writes).is_empty()
    assert_that(_snapshot(author)).is_equal_to(before)


def test_successful_pin_publication_returns_original_and_retains_modes(
    transaction_author: Path,
) -> None:
    """Publish the new pin and retain the original permission bits."""
    root = transaction_author
    path = root / "ai-skills.yaml"
    raw = legacy_documents(read_document(path))["vendors.yaml"]["vendors"]
    raw[0]["sha"] = "f" * 40
    before = _snapshot(root)
    original = path.read_bytes().decode("utf-8")
    assert_that(write_vendors(path=path, vendors=raw)).is_equal_to(original)
    assert_that(read_document(path)["vendors"][0]["sha"]).is_equal_to("f" * 40)
    assert_that(read_document(root / "vendors.yaml")["vendors"]).is_equal_to(raw)
    assert_that(write_legacy(root, check=True)).is_zero()
    after = _snapshot(root)
    assert_that(
        {name: state[1] for name, state in after.items() if state is not None}
    ).is_equal_to(
        {name: state[1] for name, state in before.items() if state is not None}
    )


@pytest.mark.parametrize(
    "field", ["extraFiles", "renameSkills", "agents", "plugins", "retained"]
)
def test_replacement_removes_only_omitted_legacy_owned_fields(
    author: Path, field: str
) -> None:
    """The production writer applies omission while preserving matching declarations."""
    path = author / "ai-skills.yaml"
    before = read_document(path)
    raw = copy.deepcopy(legacy_documents(before)["vendors.yaml"]["vendors"])
    if field == "plugins":
        raw[0].pop("plugins")
        # Removing publications requires the author to remove their exports too.
        before["exports"] = [
            value
            for value in before["exports"]
            if not value.startswith(f"{raw[0]['id']}/")
        ]
        path.write_text(dump_document(before))
    elif field != "retained":
        raw[0]["plugins"][0].pop(field)
    write_vendors(path, raw)
    after = read_document(path)
    mapping = after["vendors"][0]["mapping"]
    assert_that(mapping["x-mapping-note"]).is_equal_to({"preserve": True})
    assert_that(after["vendors"][0]["x-vendor-note"]).is_equal_to("preserve")
    assert_that(after["vendors"][1:]).is_equal_to(before["vendors"][1:])
    if field == "plugins":
        assert_that(mapping).does_not_contain_key("packages")
    else:
        package = mapping["packages"][0]
        assert_that(package["capabilities"]).is_equal_to({"teach": {"id": "stable"}})
        assert_that(package["x-package-note"]).is_equal_to("preserve")
        for optional in ("extraFiles", "renameSkills", "agents"):
            if optional == field:
                assert_that(package).does_not_contain_key(optional)
            else:
                assert_that(package[optional]).is_equal_to(
                    before["vendors"][0]["mapping"]["packages"][0][optional]
                )
    assert_that(legacy_documents(after)["vendors.yaml"]["vendors"]).is_equal_to(raw)


def test_management_add_update_and_writer_remove_are_lintable(
    author: Path, monkeypatch: pytest.MonkeyPatch, check_yaml: Callable[[Path], None]
) -> None:
    """Real author management mutations and removal roundtrip through the renderer."""
    # Acquisition is separate; exercise the real local write/validate path.
    monkeypatch.setattr(manage, "refresh", lambda **kwargs: write_legacy(author))
    path = author / "ai-skills.yaml"
    original = read_document(path)
    manage.add(
        repo_root=author,
        vendor_id="new-vendor",
        repo="example/new-vendor",
        sha="a" * 40,
        skill_roots=("skills",),
        license_name="MIT",
        homepage="https://example.test",
        display_ref=None,
        branch="main",
    )
    for name in ("ai-skills.yaml", "bundles.yaml", "vendors.yaml"):
        check_yaml(author / name)
    manage.update(
        repo_root=author,
        vendor_id="new-vendor",
        repo=None,
        sha="b" * 40,
        skill_roots=("skills", "extras"),
        license_name=None,
        homepage=None,
        display_ref=None,
        clear_branch=True,
    )
    assert_that(
        read_document(path)["vendors"][-1]["mapping"]["skillRoots"]
    ).is_equal_to(["skills", "extras"])
    for name in ("ai-skills.yaml", "bundles.yaml", "vendors.yaml"):
        check_yaml(author / name)
    raw = legacy_documents(read_document(path))["vendors.yaml"]["vendors"]
    manage._write_registry(registry_path=path, vendors=raw[:-1])
    assert_that(read_document(path)).is_equal_to(original)
    assert_that(write_legacy(author, check=True)).is_zero()
    for name in ("ai-skills.yaml", "bundles.yaml", "vendors.yaml"):
        check_yaml(author / name)
