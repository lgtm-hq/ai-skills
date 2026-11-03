"""Exercise publication and refresh rollback at real destination I/O boundaries."""

import shutil
import stat
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.legacy import render_legacy, write_legacy
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.vendors import manage

ROOT = Path(__file__).resolve().parents[1]
REGISTRIES = ("bundles.yaml", "vendors.yaml")


def _snapshot(paths: list[Path]) -> dict[Path, tuple[bytes, int] | None]:
    """Observe exact bytes, modes and absence independently of production helpers."""
    return {
        path: (
            (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            if path.exists()
            else None
        )
        for path in paths
    }


@pytest.fixture
def author(tmp_path: Path) -> Path:
    """Seed valid real payloads and deliberately noncanonical compatibility bytes."""
    shutil.copytree(src=ROOT / "skills", dst=tmp_path / "skills")
    for name in ("ai-skills.yaml", *REGISTRIES):
        path = tmp_path / name
        path.write_bytes(
            b"# original\r\n" + (ROOT / name).read_bytes().replace(b"\n", b"\r\n")
        )
        path.chmod(0o640 if name == "bundles.yaml" else 0o600)
    return tmp_path


def _change_manifest(root: Path) -> None:
    """Change both projected registries through schema-valid declarations."""
    path = root / "ai-skills.yaml"
    data = read_document(path)
    data["packages"][0]["description"] = "Changed publication description"
    data["vendors"][0]["sha"] = "f" * 40
    path.write_text(dump_document(data))


@pytest.mark.parametrize("failed_name", REGISTRIES)
@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize(
    "absent", [(), REGISTRIES, ("bundles.yaml",), ("vendors.yaml",)]
)
def test_direct_legacy_failure_restores_both_destinations(
    author: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_name: str,
    partial: bool,
    absent: tuple[str, ...],
) -> None:
    """First/second destination failures restore partial writes and original absence."""
    _change_manifest(author)
    expected = render_legacy(author)
    for name in absent:
        (author / name).unlink()
    paths = [author / name for name in REGISTRIES]
    before = _snapshot(paths)
    for path in paths:
        previous = before[path]
        if previous is not None:
            assert_that(expected[path]).is_not_equal_to(previous[0])
    real_write = Path.write_bytes
    failure = PermissionError("primary destination failure")
    failed = False

    def publish(path: Path, content: bytes) -> int:
        """Fail once at an actual destination, leaving rendering and rollback real."""
        nonlocal failed
        if path == author / failed_name and not failed:
            failed = True
            if partial:
                real_write(path, b"partial publication")
                path.chmod(0o666)
            raise failure
        return real_write(path, content)

    monkeypatch.setattr(Path, "write_bytes", publish)
    with pytest.raises(PermissionError) as caught:
        write_legacy(author)
    assert_that(caught.value).is_same_as(failure)
    assert_that(failed).is_true()
    assert_that(_snapshot(paths)).is_equal_to(before)


@pytest.mark.parametrize("blocked_name", REGISTRIES)
def test_direct_cleanup_attempts_every_destination(
    author: Path,
    monkeypatch: pytest.MonkeyPatch,
    blocked_name: str,
) -> None:
    """A cleanup write error annotates the primary error and permits other cleanup."""
    _change_manifest(author)
    paths = [author / name for name in REGISTRIES]
    before = _snapshot(paths)
    real_write = Path.write_bytes
    failure = PermissionError("primary publication failure")
    failed = False

    def publish(path: Path, content: bytes) -> int:
        """Interrupt the second publication, then deny one restoration."""
        nonlocal failed
        if path == author / "vendors.yaml" and not failed:
            failed = True
            real_write(path, b"partial vendor registry")
            raise failure
        if failed and path == author / blocked_name:
            raise PermissionError("cleanup write denied")
        return real_write(path, content)

    monkeypatch.setattr(Path, "write_bytes", publish)
    with pytest.raises(PermissionError) as caught:
        write_legacy(author)
    assert_that(caught.value).is_same_as(failure)
    assert_that("\n".join(caught.value.__notes__)).contains(blocked_name, "cleanup")
    other = author / next(name for name in REGISTRIES if name != blocked_name)
    assert_that(_snapshot([other])[other]).is_equal_to(before[other])


def test_real_render_check_cli_and_noop_controls(
    author: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Actual render/check stay zero-write; ordinary CLI publication and no-op work."""
    _change_manifest(author)
    paths = [author / name for name in REGISTRIES]
    before = _snapshot(paths)
    real_write = Path.write_bytes
    writes: list[Path] = []

    def observe(path: Path, content: bytes) -> int:
        """Count only public destinations, never private renderer scratch files."""
        if path in paths:
            writes.append(path)
        return real_write(path, content)

    monkeypatch.setattr(Path, "write_bytes", observe)
    expected = render_legacy(author)
    assert_that(write_legacy(author, check=True)).is_equal_to(1)
    args = ["--repo-root", str(author), "manifest", "legacy"]
    assert_that(cli.main([*args, "--check"])).is_equal_to(1)
    assert_that(writes).is_empty()
    assert_that(_snapshot(paths)).is_equal_to(before)
    assert_that(cli.main(args)).is_zero()
    assert_that(writes).is_equal_to(paths)
    assert_that({path: path.read_bytes() for path in paths}).is_equal_to(expected)
    writes.clear()
    assert_that(cli.main(args)).is_zero()
    assert_that(cli.main([*args, "--check"])).is_zero()
    assert_that(writes).is_empty()


@pytest.mark.parametrize(
    "blocked",
    [
        None,
        "ai-skills.yaml",
        "bundles.yaml",
        "vendors.yaml",
        "NOTICE.md",
        "vendor-indexes/a.json",
        "npm/ai-skills/NOTICE.md",
    ],
)
@pytest.mark.parametrize("via_update", [False, True])
@pytest.mark.parametrize("absent", [False, True])
def test_refresh_cleanup_preserves_primary_and_restores_independently(
    author: Path,
    monkeypatch: pytest.MonkeyPatch,
    blocked: str | None,
    via_update: bool,
    absent: bool,
) -> None:
    """Only refresh acquisition is faked; actual rollback I/O fails independently."""
    registry = author / "ai-skills.yaml"
    original = registry.read_bytes().decode()
    if absent:
        for name in REGISTRIES:
            (author / name).unlink()
    for name in ("NOTICE.md", "vendor-indexes/a.json", "vendor-indexes/b.json"):
        path = author / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"original artifact\r\n")
        path.chmod(0o640)
    paths = [
        author / name
        for name in (
            "ai-skills.yaml",
            *REGISTRIES,
            "NOTICE.md",
            "vendor-indexes/a.json",
            "vendor-indexes/b.json",
            "npm/ai-skills/NOTICE.md",
        )
    ]
    before = _snapshot(paths)
    failure = ValueError("primary refresh failure")
    real_write, real_unlink = Path.write_bytes, Path.unlink
    cleaning = False

    def refresh(*, repo_root: Path) -> None:
        """Mutate every snapshot class then fail at the acquisition boundary."""
        nonlocal cleaning
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"partial refresh")
            path.chmod(0o666)
        cleaning = True
        raise failure

    def write(path: Path, content: bytes) -> int:
        """Deny one actual cleanup destination after refresh has failed."""
        if cleaning and blocked is not None and path == author / blocked:
            raise PermissionError("cleanup destination denied")
        return real_write(path, content)

    def unlink(path: Path, missing_ok: bool = False) -> None:
        """Deny deletion of one generated destination that was originally absent."""
        if cleaning and blocked is not None and path == author / blocked:
            raise PermissionError("cleanup deletion denied")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(manage, "refresh", refresh)
    monkeypatch.setattr(Path, "write_bytes", write)
    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(ValueError) as caught:
        if via_update:
            manage.update(
                repo_root=author,
                vendor_id=read_document(registry)["vendors"][0]["id"],
                repo=None,
                sha="f" * 40,
                skill_roots=None,
                license_name=None,
                homepage=None,
                display_ref=None,
            )
        else:
            manage._refresh_or_restore(
                repo_root=author, registry_path=registry, original=original
            )
    assert_that(caught.value).is_same_as(failure)
    if blocked:
        assert_that("\n".join(caught.value.__notes__)).contains(blocked, "cleanup")
    after = _snapshot(paths)
    for path, state in before.items():
        if blocked is None or path != author / blocked:
            assert_that(after[path]).described_as(str(path)).is_equal_to(state)
