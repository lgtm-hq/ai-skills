"""Content-addressed source cache: canonical trees, verification and atomic writes."""

import gzip
import io
import os
import shutil
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine.bake import vendor_plugins
from ai_skills_engine.registry.vendor import Vendor
from ai_skills_engine.source_cache import (
    CacheCorruptError,
    CacheMissError,
    SourceCache,
    SourceMismatchError,
    cache_root,
    canonical_source_tar,
    digest_bytes,
    extract_canonical,
    materialize,
)

SHA = "0123456789abcdef0123456789abcdef01234567"


def _vendor() -> Vendor:
    """Describe the fixture pin.

    Returns:
        Registry vendor for ``upstream/tools`` at a fixed SHA.
    """
    return Vendor(
        id="upstream",
        repo="upstream/tools",
        sha=SHA,
        skill_roots=("skills",),
        license="",
        homepage="",
    )


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Create a small vendor tree with links, an empty directory and modes.

    Args:
        tmp_path: Test directory.

    Returns:
        Source tree root.
    """
    root = tmp_path / "tree"
    (root / "skills/help").mkdir(parents=True)
    (root / "skills/help/SKILL.md").write_text("---\nname: help\n---\nHelp.\n")
    (root / "skills/help/run.sh").write_text("echo never executed\n")
    (root / "skills/help/run.sh").chmod(0o755)
    (root / "empty").mkdir()
    (root / "CLAUDE.md").write_text("Navigation.\n")
    (root / "AGENTS.md").symlink_to("CLAUDE.md")
    return root


def _snapshot(root: Path) -> dict[str, tuple[str, bytes | str | None, bool]]:
    """Observe nodes lexically without following links.

    Args:
        root: Tree root.

    Returns:
        Relative path to kind, bytes or link target, and owner-execute bit.
    """
    nodes: dict[str, tuple[str, bytes | str | None, bool]] = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            nodes[name] = ("link", os.readlink(path), False)
        elif path.is_dir():
            nodes[name] = ("dir", None, False)
        else:
            nodes[name] = ("file", path.read_bytes(), bool(path.stat().st_mode & 0o100))
    return nodes


def test_cache_root_precedence(tmp_path: Path) -> None:
    """AI_SKILLS_CACHE wins, then an absolute XDG_CACHE_HOME, then ~/.cache."""
    explicit = str(tmp_path / "explicit")
    assert_that(
        cache_root({"AI_SKILLS_CACHE": explicit, "XDG_CACHE_HOME": "/xdg"})
    ).is_equal_to(Path(explicit))
    assert_that(cache_root({"XDG_CACHE_HOME": "/xdg"})).is_equal_to(
        Path("/xdg/ai-skills")
    )
    home = Path.home() / ".cache/ai-skills"
    assert_that(cache_root({"XDG_CACHE_HOME": "relative"})).is_equal_to(home)
    assert_that(cache_root({"AI_SKILLS_CACHE": ""})).is_equal_to(home)


def test_canonical_tree_ignores_times_and_group_bits(
    tree: Path, tmp_path: Path
) -> None:
    """Equal trees hash equally; links, empty directories and +x round-trip."""
    copy = tmp_path / "copy"
    shutil.copytree(tree, copy, symlinks=True)
    (copy / "CLAUDE.md").chmod(0o664)
    os.utime(copy / "skills/help/SKILL.md", (1, 1))
    first = canonical_source_tar(root=tree, vendor="upstream")
    assert_that(canonical_source_tar(root=copy, vendor="upstream")).is_equal_to(first)
    extracted = tmp_path / "extracted"
    extract_canonical(data=first, dest=extracted)
    assert_that(_snapshot(extracted)).is_equal_to(_snapshot(tree))
    assert_that(canonical_source_tar(root=extracted, vendor="upstream")).is_equal_to(
        first
    )
    (copy / "CLAUDE.md").chmod(0o755)
    assert_that(canonical_source_tar(root=copy, vendor="upstream")).is_not_equal_to(
        first
    )
    with tarfile.open(fileobj=io.BytesIO(first), mode="r:") as archive:
        members = archive.getmembers()
    assert_that({(item.uid, item.gid, item.mtime) for item in members}).is_equal_to(
        {(0, 0, 0)}
    )
    assert_that([item.name for item in members]).is_sorted()


def test_special_mode_bits_are_rejected(tree: Path) -> None:
    """Setuid inputs fail before they can enter the cache."""
    (tree / "CLAUDE.md").chmod(0o4755)
    with pytest.raises(ValueError, match="special mode bits"):
        canonical_source_tar(root=tree, vendor="upstream")


def test_source_digest_survives_forge_recompression(tree: Path, tmp_path: Path) -> None:
    """Different gzip bytes for one tree extract to the same source digest."""
    digests = set()
    archives = set()
    for level, mtime in ((1, 0), (9, 1234567890)):
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as archive:
            archive.add(tree, arcname="owner-repo-" + SHA[:7])
        payload = gzip.compress(raw.getvalue(), compresslevel=level, mtime=mtime)
        archives.add(payload)
        destination = tmp_path / f"extracted-{level}"
        vendor_plugins._extract_tarball(payload=payload, dest=destination)
        digests.add(digest_bytes(canonical_source_tar(root=destination, vendor="x")))
    assert_that(archives).is_length(2)
    assert_that(digests).is_length(1)


def test_reads_verify_and_report_distinct_failures(tree: Path, tmp_path: Path) -> None:
    """Missing, corrupted and malformed-ref entries fail with their own messages."""
    cache = SourceCache(root=tmp_path / "cache")
    data = canonical_source_tar(root=tree, vendor="upstream")
    digest = cache.store(
        data=data, repo="upstream/tools", revision=SHA, label="upstream", expected=None
    )
    assert_that(digest).is_equal_to(digest_bytes(data))
    assert_that(cache.lookup(repo="upstream/tools", revision=SHA)).is_equal_to(digest)
    assert_that(cache.read(digest, label="upstream")).is_equal_to(data)
    assert_that(
        cache.source_path(digest).relative_to(cache.root).as_posix()
    ).is_equal_to("sources/sha256-" + digest[7:] + ".tar")
    with pytest.raises(CacheMissError, match="lock --fetch"):
        cache.read("sha256:" + "0" * 64, label="upstream")
    path = cache.source_path(digest)
    path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    with pytest.raises(CacheCorruptError, match="Corrupted source cache entry"):
        cache.read(digest, label="upstream")
    cache.ref_path(repo="upstream/tools", revision=SHA).write_text("garbage\n")
    with pytest.raises(CacheCorruptError, match="Corrupted source cache ref"):
        cache.lookup(repo="upstream/tools", revision=SHA)
    for repo, revision in (("../tools", SHA), ("a/..", SHA), ("a/b", "HEAD")):
        with pytest.raises(ValueError, match="Invalid pinned source coordinate"):
            cache.ref_path(repo=repo, revision=revision)


def test_store_rejects_locked_digest_mismatch_without_writing(
    tree: Path, tmp_path: Path
) -> None:
    """Bytes that disagree with the lock never enter the cache."""
    cache = SourceCache(root=tmp_path / "cache")
    data = canonical_source_tar(root=tree, vendor="upstream")
    with pytest.raises(SourceMismatchError, match="ai-skills.lock records"):
        cache.store(
            data=data,
            repo="upstream/tools",
            revision=SHA,
            label="upstream",
            expected="sha256:" + "0" * 64,
        )
    assert_that(cache.root.exists()).is_false()


@pytest.mark.parametrize("member", ["escape", "link-parent", "absolute", "device"])
def test_unsafe_cached_members_never_extract(tmp_path: Path, member: str) -> None:
    """Even digest-valid hostile archives cannot write outside the destination."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        if member == "link-parent":
            link = tarfile.TarInfo("outside")
            link.type = tarfile.SYMTYPE
            link.linkname = str(tmp_path)
            archive.addfile(link)
            name = "outside/written.txt"
        else:
            name = {"escape": "../written.txt", "absolute": "/written.txt"}.get(
                member, "device"
            )
        entry = tarfile.TarInfo(name)
        if member == "device":
            entry.type = tarfile.CHRTYPE
            archive.addfile(entry)
        else:
            entry.size = 1
            archive.addfile(entry, io.BytesIO(b"x"))
    cache = SourceCache(root=tmp_path / "cache")
    data = raw.getvalue()
    digest = digest_bytes(data)
    cache.source_path(digest).parent.mkdir(parents=True)
    cache.source_path(digest).write_bytes(data)
    with pytest.raises(CacheCorruptError):
        cache.extract(digest, dest=tmp_path / "dest", label="upstream")
    assert_that((tmp_path / "written.txt").exists()).is_false()


def test_materialize_fetches_once_then_reads_cache(tree: Path, tmp_path: Path) -> None:
    """Cold and warm paths extract identical bytes; warm never acquires."""
    cache = SourceCache(root=tmp_path / "cache")
    calls: list[Path] = []

    def fetch(*, vendor: Vendor, dest: Path) -> None:
        """Supply the local fixture as the pinned upstream archive."""
        calls.append(dest)
        shutil.copytree(tree, dest, symlinks=True)

    cold = materialize(
        cache=cache, vendor=_vendor(), dest=tmp_path / "a", fetcher=fetch
    )
    warm = materialize(
        cache=cache, vendor=_vendor(), dest=tmp_path / "b", fetcher=fetch
    )
    assert_that(calls).is_length(1)
    assert_that(cold).is_equal_to(warm)
    assert_that(_snapshot(tmp_path / "a")).is_equal_to(_snapshot(tmp_path / "b"))
    assert_that(list(tmp_path.glob(".ai-skills-fetch-*"))).is_empty()
    offline = SourceCache(root=tmp_path / "empty")
    with pytest.raises(CacheMissError, match="vendor upstream .*lock --fetch"):
        materialize(cache=offline, vendor=_vendor(), dest=tmp_path / "c", fetcher=None)
    with pytest.raises(SourceMismatchError):
        materialize(
            cache=offline,
            vendor=_vendor(),
            dest=tmp_path / "d",
            fetcher=fetch,
            expected="sha256:" + "0" * 64,
        )
    assert_that(offline.root.exists()).is_false()


def test_unsafe_fetched_tree_is_never_cached(tmp_path: Path) -> None:
    """Acquired trees pass structural ingestion checks before storage."""
    cache = SourceCache(root=tmp_path / "cache")

    def fetch(*, vendor: Vendor, dest: Path) -> None:
        """Return a tree containing a FIFO."""
        dest.mkdir()
        os.mkfifo(dest / "pipe")

    with pytest.raises(ValueError, match="unsupported file type"):
        materialize(cache=cache, vendor=_vendor(), dest=tmp_path / "a", fetcher=fetch)
    assert_that(cache.root.exists()).is_false()


def test_concurrent_writers_publish_complete_entries(
    tree: Path, tmp_path: Path
) -> None:
    """Parallel stores of one source race harmlessly via temp, fsync and rename."""
    cache = SourceCache(root=tmp_path / "cache")
    data = canonical_source_tar(root=tree, vendor="upstream")

    def store() -> str:
        """Store the same canonical bytes repeatedly.

        Returns:
            Last stored digest.
        """
        digests = {
            cache.store(
                data=data,
                repo="upstream/tools",
                revision=SHA,
                label="upstream",
                expected=None,
            )
            for _ in range(5)
        }
        return digests.pop()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [pool.submit(store) for _ in range(8)]
        assert_that({item.result() for item in results}).is_equal_to(
            {digest_bytes(data)}
        )
    names = sorted(path.name for path in cache.root.rglob("*") if path.is_file())
    assert_that(names).is_equal_to(
        sorted([SHA, "sha256-" + digest_bytes(data)[7:] + ".tar"])
    )
    assert_that(cache.read(digest_bytes(data), label="upstream")).is_equal_to(data)


def test_interrupted_write_leaves_no_partial_entry(
    tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure before rename publishes nothing and removes the temporary file."""
    cache = SourceCache(root=tmp_path / "cache")
    data = canonical_source_tar(root=tree, vendor="upstream")

    def fail(*_args: object) -> None:
        """Simulate a crash at the rename step."""
        raise OSError("interrupted")

    monkeypatch.setattr("ai_skills_engine.atomic_write.os.replace", fail)
    with pytest.raises(OSError, match="interrupted"):
        cache.store(
            data=data,
            repo="upstream/tools",
            revision=SHA,
            label="upstream",
            expected=None,
        )
    assert_that([path for path in cache.root.rglob("*") if path.is_file()]).is_empty()


def test_legacy_bake_materialization_reads_through_cache(
    tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compatibility baker fetches a pin once, then works with HTTP disabled."""
    calls: list[str] = []

    def fetch(*, vendor: Vendor, dest: Path) -> None:
        """Supply the local fixture as the pinned upstream archive."""
        calls.append(vendor.sha)
        shutil.copytree(tree, dest, symlinks=True)

    def offline(**_kwargs: object) -> bytes:
        """Fail on any HTTP request."""
        raise AssertionError("network access")

    monkeypatch.setattr(vendor_plugins, "_fetch_vendor_tree", fetch)
    monkeypatch.setattr(vendor_plugins, "_http_get_bytes", offline)
    first = vendor_plugins._materialize_vendor_tree(
        vendor=_vendor(), trees={}, temporary_root=tmp_path / "first"
    )
    monkeypatch.setattr(vendor_plugins, "_fetch_vendor_tree", offline)
    second = vendor_plugins._materialize_vendor_tree(
        vendor=_vendor(), trees={}, temporary_root=tmp_path / "second"
    )
    assert_that(calls).is_equal_to([SHA])
    assert_that(_snapshot(first)).is_equal_to(_snapshot(second))
    # The legacy bake-only documentation alias exception still applies.
    assert_that((second / "AGENTS.md").exists()).is_false()
    assert_that((tree / "AGENTS.md").is_symlink()).is_true()
