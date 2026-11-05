"""Synthetic, network-free archive and streaming resource-limit regressions."""

from __future__ import annotations

import gzip
import tarfile
from collections.abc import Callable
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from assertpy import assert_that

from ai_skills_engine.bake import vendor_plugins as baker
from ai_skills_engine.registry.ingest_limits import IngestLimits

pytest_plugins = ["ingest_helpers"]


@pytest.mark.parametrize(
    "name,target",
    [
        ("link", "asset"),
        ("link", "../root/asset"),
        ("nested/link", "../../root/asset"),
        ("quoted ' dir/link", "../../root/asset"),
        ("nested/link", "../asset"),
        ("link", "../../outside"),
        ("link", "/root/asset"),
        ("link", "../other/asset"),
        ("link", "..\\outside"),
    ],
    ids=[
        "direct",
        "reenter",
        "nested-reenter",
        "quoted",
        "nested",
        "outside",
        "absolute",
        "sibling-root",
        "backslash",
    ],
)
def test_symlink_targets_use_original_archive_coordinates(
    archive_destination: Path,
    name: str,
    target: str,
) -> None:
    """Translate safe targets and preserve the destination on rejection."""
    from inventory_helpers import inventory_snapshot

    destination = archive_destination
    existed = destination.exists()
    before = inventory_snapshot(destination) if existed else {}
    inode = destination.stat().st_ino if existed else None
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz", compresslevel=0) as archive:
        asset = tarfile.TarInfo("root/asset")
        data = b"ordinary fixture bytes\n"
        asset.size = len(data)
        archive.addfile(asset, BytesIO(data))
        link = tarfile.TarInfo("root/" + name)
        link.type = tarfile.SYMTYPE
        link.linkname = target
        archive.addfile(link)
    accepted = target in {"asset", "../root/asset", "../../root/asset", "../asset"}
    if accepted:
        baker._extract_tarball(
            payload=output.getvalue(), dest=destination, vendor_id="synthetic"
        )
        assert_that((destination / name).is_symlink()).is_true()
        assert_that((destination / name).read_bytes()).is_equal_to(data)
        assert_that((destination / name).resolve()).is_equal_to(destination / "asset")
        assert_that((destination / "asset").stat().st_mode & 0o7777).is_equal_to(0o644)
    else:
        with pytest.raises((ValueError, RuntimeError)):
            baker._extract_tarball(
                payload=output.getvalue(), dest=destination, vendor_id="synthetic"
            )
        if existed:
            assert_that(inventory_snapshot(destination)).is_equal_to(before)
            assert_that(destination.stat().st_ino).is_equal_to(inode)
        else:
            assert_that(destination.exists()).is_false()


def test_archive_symlink_cycle_cannot_publish(archive_destination: Path) -> None:
    """The data filter still rejects a cycle while staging, preserving old bytes."""
    from inventory_helpers import inventory_snapshot

    destination = archive_destination
    existed = destination.exists()
    before = inventory_snapshot(destination) if existed else {}
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz", compresslevel=0) as archive:
        for name, target in (("one", "two"), ("two", "one"), ("two/child", "one")):
            member = tarfile.TarInfo("root/" + name)
            member.type = tarfile.SYMTYPE
            member.linkname = target
            archive.addfile(member)
    with pytest.raises((ValueError, RuntimeError)):
        baker._extract_tarball(
            payload=output.getvalue(), dest=destination, vendor_id="synthetic"
        )
    if existed:
        assert_that(inventory_snapshot(destination)).is_equal_to(before)
    else:
        assert_that(destination.exists()).is_false()


def test_root_layout_preflight_preserves_rejected_destination(
    root_archive: tuple[bytes, str | None], archive_destination: Path
) -> None:
    """Actual baker extraction rejects invalid roots before any publication."""
    payload, error = root_archive
    destination = archive_destination
    existed = destination.exists()
    inode = destination.stat().st_ino if existed else None
    sentinel_inode = (destination / "sentinel").stat().st_ino if existed else None
    if error is None:
        baker._extract_tarball(
            payload=payload, dest=destination, vendor_id="synthetic-vendor"
        )
        assert_that(sorted(path.name for path in destination.iterdir())).is_equal_to(
            ["asset.txt", "other.txt"]
        )
        asset = destination / "asset.txt"
        assert_that(asset.read_bytes()).is_equal_to(b"actual fixture payload\n")
        assert_that(asset.stat().st_mode & 0o7777).is_equal_to(0o644)
        other = destination / "other.txt"
        assert_that(other.read_bytes()).is_equal_to(b"second fixture payload\n")
        assert_that(other.stat().st_mode & 0o7777).is_equal_to(0o644)
        return
    with pytest.raises(ValueError) as raised:
        baker._extract_tarball(
            payload=payload, dest=destination, vendor_id="synthetic-vendor"
        )
    assert_that(str(raised.value)).contains(
        "synthetic-vendor", error, "directory"
    ).does_not_contain("AKIA" + "A" * 16)
    if error == "top-level":
        assert_that(str(raised.value)).contains("loose")
    if ("AKIA" + "A" * 16).encode() in payload:
        assert_that(str(raised.value)).contains("[REDACTED]")
    if existed:
        sentinel = destination / "sentinel"
        assert_that(list(destination.iterdir())).is_equal_to([sentinel])
        assert_that(sentinel.read_bytes()).is_equal_to(b"\x00original sentinel\xff\n")
        assert_that(sentinel.stat().st_mode & 0o7777).is_equal_to(0o640)
        assert_that(sentinel.stat().st_ino).is_equal_to(sentinel_inode)
        assert_that(destination.stat().st_mode & 0o7777).is_equal_to(0o750)
        assert_that(destination.stat().st_ino).is_equal_to(inode)
        assert_that(list(destination.parent.iterdir())).is_equal_to([destination])
    else:
        assert_that(destination.parent.exists()).is_false()


def archive_bytes(
    *, mode: int = 0o644, kind: bytes = tarfile.REGTYPE, count: int = 1
) -> bytes:
    """Build small real tar bytes without fetching any content.

    Args:
        mode: Raw permission bits.
        kind: Raw tar type flag.
        count: Number of members.

    Returns:
        Gzip-compressed fixture bytes.
    """
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for index in range(count):
            member = tarfile.TarInfo(f"root/asset-{index}")
            member.uname = "synthetic-fixture-marker"
            member.mode = mode
            member.type = kind
            member.linkname = "asset-0"
            data = bytes(range(256)) if kind == tarfile.REGTYPE else b""
            member.size = len(data)
            archive.addfile(member, BytesIO(data))
    return output.getvalue()


@pytest.mark.parametrize(
    "limit,maximum",
    [
        ("download_bytes", 1),
        ("archive_members", 1),
        ("archive_bytes", 100),
        ("member_bytes", 100),
        ("compression_ratio", 1),
    ],
)
def test_every_archive_limit_rejects_without_destination_writes(
    tmp_path: Path, limit: str, maximum: int
) -> None:
    """Every limit fails contextually before extraction or destination replacement."""
    from ai_skills_engine.manifest.codec import field_key

    destination = tmp_path / "tree"
    destination.mkdir()
    sentinel = destination / "sentinel"
    sentinel.write_bytes(b"untouched")
    inode = destination.stat().st_ino
    overrides: dict[str, Any] = {limit: maximum}
    with pytest.raises(ValueError) as raised:
        baker._extract_tarball(
            payload=archive_bytes(count=2),
            dest=destination,
            vendor_id="synthetic-vendor",
            limits=replace(IngestLimits(), **overrides),
        )
    assert_that(str(raised.value)).contains(
        "synthetic-vendor", field_key(limit), "limit", ":"
    )
    assert_that(list(destination.iterdir())).is_equal_to([sentinel])
    assert_that(sentinel.read_bytes()).is_equal_to(b"untouched")
    assert_that(destination.stat().st_ino).is_equal_to(inode)


@pytest.mark.parametrize(
    "kind",
    [
        tarfile.LNKTYPE,
        tarfile.CHRTYPE,
        tarfile.BLKTYPE,
        tarfile.FIFOTYPE,
        tarfile.GNUTYPE_SPARSE,
    ],
)
def test_special_member_types_are_rejected_at_headers(
    tmp_path: Path, kind: bytes
) -> None:
    """Hard links, devices, FIFOs and sparse headers cannot enter extraction."""
    dest = tmp_path / "tree"
    with pytest.raises(
        ValueError, match="synthetic-vendor.*asset-0.*unsupported archive member"
    ):
        baker._extract_tarball(
            payload=archive_bytes(kind=kind), dest=dest, vendor_id="synthetic-vendor"
        )
    assert_that(dest.exists()).is_false()


@pytest.mark.parametrize("mode", [0o4644, 0o2644, 0o1644])
def test_special_mode_bits_rejected_before_data_filter(
    tmp_path: Path, mode: int
) -> None:
    """The data filter cannot erase evidence of a special input permission."""
    with pytest.raises(ValueError, match="special mode bits"):
        baker._extract_tarball(
            payload=archive_bytes(mode=mode),
            dest=tmp_path / "tree",
            vendor_id="synthetic",
        )
    assert_that((tmp_path / "tree").exists()).is_false()


@pytest.mark.parametrize(
    "kind",
    [
        tarfile.XHDTYPE,
        tarfile.XGLTYPE,
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_LONGLINK,
    ],
)
def test_extended_metadata_is_bounded_before_body_read(
    tmp_path: Path, kind: bytes
) -> None:
    """A huge extended-header declaration fails before tarfile reads its body."""
    header = tarfile.TarInfo("root/oversized-metadata")
    header.type = kind
    header.size = 30_000_000
    # No body exists: an attempted body read would fail as truncated archive.
    payload = gzip.compress(header.tobuf())
    with pytest.raises(ValueError, match="synthetic.*oversized-metadata.*memberBytes"):
        baker._extract_tarball(
            payload=payload, dest=tmp_path / "tree", vendor_id="synthetic"
        )
    assert_that((tmp_path / "tree").exists()).is_false()


def test_effective_pax_size_cannot_bypass_member_limit(tmp_path: Path) -> None:
    """PAX size overrides are checked again after extended-header processing."""
    output = BytesIO()
    with tarfile.open(
        fileobj=output, mode="w:gz", format=tarfile.PAX_FORMAT
    ) as archive:
        member = tarfile.TarInfo("root/data")
        member.pax_headers = {"size": "30000000"}
        member.size = 1
        archive.addfile(member, BytesIO(b"a"))
    with pytest.raises(ValueError, match="memberBytes"):
        baker._extract_tarball(
            payload=output.getvalue(), dest=tmp_path / "tree", vendor_id="synthetic"
        )


def test_tar_iteration_does_not_collect_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real extraction path streams next() and never calls getmembers()."""

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        """Fail if member accumulation is attempted."""
        pytest.fail("getmembers called")

    monkeypatch.setattr(tarfile.TarFile, "getmembers", forbidden)
    dest = tmp_path / "tree"
    baker._extract_tarball(
        payload=archive_bytes(mode=0o775), dest=dest, vendor_id="synthetic"
    )
    assert_that((dest / "asset-0").read_bytes()).is_equal_to(bytes(range(256)))
    assert_that((dest / "asset-0").stat().st_mode & 0o7777).is_equal_to(0o755)


def test_bypassed_header_hook_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tarfile that stops calling the private header hook cannot extract."""
    base = vars(tarfile.TarInfo)["_proc_member"]

    def renamed_hook(cls: Any, archive: Any, **_kwargs: Any) -> Any:
        """Parse a header as if tarfile had renamed ``_proc_member``."""
        block = archive.fileobj.read(tarfile.BLOCKSIZE)
        member = cls.frombuf(block, archive.encoding, archive.errors)
        member.offset = archive.fileobj.tell() - tarfile.BLOCKSIZE
        return base(member, archive)

    # Newer runtimes route fromtarfile() through _fromtarfile(); patch either.
    entry = (
        "_fromtarfile" if hasattr(tarfile.TarInfo, "_fromtarfile") else "fromtarfile"
    )
    hook = classmethod(cast(Callable[..., Any], renamed_hook))
    monkeypatch.setattr(tarfile.TarInfo, entry, hook)
    dest = tmp_path / "tree"
    with pytest.raises(ValueError, match="tar header checks did not run"):
        baker._extract_tarball(
            payload=archive_bytes(mode=0o644), dest=dest, vendor_id="synthetic"
        )
    assert_that(dest.exists()).is_false()


@pytest.mark.parametrize("length", ["10000", None, "1"])
def test_streaming_download_stops_at_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, length: str | None
) -> None:
    """Content-Length is checked first and missing/lying headers stay bounded."""
    del tmp_path
    calls: list[int] = []
    body = BytesIO(b"a" * 1000)

    def read(amount: int) -> bytes:
        """Record bounded read requests for the synthetic HTTP stream."""
        calls.append(amount)
        return body.read(amount)

    response = SimpleNamespace(
        status=200,
        getheader=lambda name: length if name == "Content-Length" else None,
        read=read,
    )
    closed: list[bool] = []
    connection = SimpleNamespace(
        request=lambda **_kwargs: None,
        getresponse=lambda: response,
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(baker, "HTTPSConnection", lambda **_kwargs: connection)
    with pytest.raises(ValueError, match="synthetic.*tarball.*downloadBytes"):
        baker._http_get_bytes(
            host="api.github.com",
            path="/synthetic/tarball",
            headers={},
            vendor_id="synthetic",
            limits=replace(IngestLimits(), download_bytes=10),
        )
    assert_that(calls).is_equal_to([] if length == "10000" else [11])
    assert_that(body.tell()).is_equal_to(0 if length == "10000" else 11)
    assert_that(closed).is_equal_to([True])


def test_download_cap_survives_redirect_and_ignores_redirect_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redirects keep consumer limits and do not buffer their irrelevant bodies."""
    reads: list[int] = []

    def body(amount: int) -> bytes:
        """Provide a synthetic over-limit terminal response."""
        reads.append(amount)
        return b"a" * amount

    responses = iter(
        [
            SimpleNamespace(
                status=302,
                getheader=lambda name: (
                    "https://codeload.github.com/synthetic"
                    if name == "Location"
                    else "99999"
                ),
                read=lambda _amount: pytest.fail("redirect body read"),
            ),
            SimpleNamespace(status=200, getheader=lambda _name: None, read=body),
        ]
    )
    monkeypatch.setattr(
        baker,
        "HTTPSConnection",
        lambda **_kwargs: SimpleNamespace(
            request=lambda **_kwargs: None,
            getresponse=lambda: next(responses),
            close=lambda: None,
        ),
    )
    with pytest.raises(ValueError, match="downloadBytes"):
        baker._http_get_bytes(
            host="api.github.com",
            path="/synthetic",
            headers={},
            vendor_id="synthetic",
            limits=replace(IngestLimits(), download_bytes=10),
        )
    assert_that(reads).is_equal_to([11])


def test_header_limit_stops_decompression_before_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Oversized member headers abort before the remaining gzip body is read."""
    header = tarfile.TarInfo("root/declared-oversize")
    header.size = 30_000_000
    payload = gzip.compress(header.tobuf() + b"a" * 1_000_000)
    requests: list[int] = []
    real_read = gzip.GzipFile.read

    def read(stream: gzip.GzipFile, amount: int = -1) -> bytes:
        """Observe requested inflation work while retaining the real decoder."""
        requests.append(amount)
        return real_read(stream, amount)

    monkeypatch.setattr(gzip.GzipFile, "read", read)
    with pytest.raises(ValueError, match="memberBytes"):
        baker._extract_tarball(
            payload=payload, dest=tmp_path / "tree", vendor_id="synthetic"
        )
    assert_that(requests).is_equal_to([tarfile.RECORDSIZE])
    assert_that((tmp_path / "tree").exists()).is_false()
