"""Bound decompression and tar headers before extraction can publish any file."""

from __future__ import annotations

import gzip
import io
import tarfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory, TemporaryFile
from typing import BinaryIO, cast

from ai_skills_engine.registry.ingest_checks import (
    CHUNK_BYTES,
    fail_limit,
    normalized_mode,
    safe_diagnostic,
)
from ai_skills_engine.registry.ingest_limits import IngestLimits


def _tarinfo_type(*, vendor: str, limits: IngestLimits) -> type[tarfile.TarInfo]:
    """Create a header validator that also bounds hidden PAX/GNU metadata.

    Args:
        vendor: Consumer vendor alias.
        limits: Effective limits.

    Returns:
        TarInfo type checking headers before tarfile allocates metadata bodies.
    """
    count = 0
    total = 0

    class CheckedTarInfo(tarfile.TarInfo):
        """Reject hostile headers before tarfile processes extended records."""

        def _proc_member(self, archive: tarfile.TarFile) -> tarfile.TarInfo | None:
            """Check each raw header, including headers hidden by PAX parsing."""
            nonlocal count, total
            count += 1
            total += self.size
            for key, actual, maximum in (
                ("archiveMembers", count, limits.archive_members),
                ("memberBytes", self.size, limits.member_bytes),
                ("archiveBytes", total, limits.archive_bytes),
            ):
                if actual > maximum:
                    fail_limit(
                        vendor=vendor, path=self.name, limit=key, maximum=maximum
                    )
            normalized_mode(mode=self.mode, vendor=vendor, path=self.name)
            if self.size < 0 or self.type not in {
                tarfile.REGTYPE,
                tarfile.AREGTYPE,
                tarfile.DIRTYPE,
                tarfile.SYMTYPE,
                tarfile.XHDTYPE,
                tarfile.XGLTYPE,
                tarfile.GNUTYPE_LONGNAME,
                tarfile.GNUTYPE_LONGLINK,
            }:
                raise ValueError(
                    safe_diagnostic(
                        f"vendor {vendor}: {self.name}: unsupported archive member type"
                    )
                )
            # typeshed omits TarInfo's metadata hook; the runtime API is required
            # to bound PAX/GNU bodies before tarfile allocates them.
            process = cast(
                Callable[[tarfile.TarInfo, tarfile.TarFile], tarfile.TarInfo | None],
                vars(tarfile.TarInfo)["_proc_member"],
            )
            return process(self, archive)

    return CheckedTarInfo


class _BoundedInflater:
    """Tee bounded gzip reads to disk while tar validates each header.

    Args:
        stream: Incremental gzip decoder.
        output: Private raw-tar spool.
        vendor: Consumer alias.
        limits: Effective policy.
        compressed_bytes: Bounded compressed input size.
    """

    def __init__(
        self,
        *,
        stream: gzip.GzipFile,
        output: BinaryIO,
        vendor: str,
        limits: IngestLimits,
        compressed_bytes: int,
    ) -> None:
        self.stream = stream
        self.output = output
        self.vendor = vendor
        self.limits = limits
        ratio_cap = compressed_bytes * limits.compression_ratio
        self.maximum = min(limits.archive_bytes, ratio_cap)
        self.limit = (
            "archiveBytes"
            if self.maximum == limits.archive_bytes
            else "compressionRatio"
        )
        self.total = 0

    def read(self, amount: int) -> bytes:
        """Read one bounded chunk, rejecting the first byte over the cap.

        Args:
            amount: Maximum requested bytes from the tar stream.

        Returns:
            Bounded inflated bytes, also spooled for the extraction pass.

        Raises:
            ValueError: On an unbounded request or resource limit violation.
        """
        if amount < 0:
            raise ValueError("unbounded tar read rejected")
        data = self.stream.read(min(amount, CHUNK_BYTES, self.maximum - self.total + 1))
        self.total += len(data)
        if self.total > self.maximum:
            fail_limit(
                vendor=self.vendor,
                path="<archive>",
                limit=self.limit,
                maximum=(
                    self.limits.archive_bytes
                    if self.limit == "archiveBytes"
                    else self.limits.compression_ratio
                ),
            )
        self.output.write(data)
        return data


def extract_tarball(
    *, payload: bytes, dest: Path, vendor: str, limits: IngestLimits
) -> None:
    """Preflight a bounded archive and then extract with the data filter.

    Raw tar bytes (including metadata and padding) count against archiveBytes
    and compressionRatio. Header checks happen before PAX/GNU allocations.
    The second pass keeps filter='data' and publishes only after complete success.

    Args:
        payload: Gzip-compressed bytes.
        dest: Unpacked tree destination.
        vendor: Vendor alias.
        limits: Effective limits.

    Raises:
        ValueError: On an unsafe header, mode, path or exceeded limit.
        RuntimeError: On invalid compressed/archive data.
    """
    from ai_skills_engine.registry.safe_tree import install_directory

    if len(payload) > limits.download_bytes:
        fail_limit(
            vendor=vendor,
            path="<archive>",
            limit="downloadBytes",
            maximum=limits.download_bytes,
        )
    # The installed typeshed lacks the Python 3.13 stream keyword. Keep the
    # runtime's documented no-member-cache API without disabling type checks.
    open_archive = cast(Callable[..., tarfile.TarFile], tarfile.open)
    try:
        with TemporaryFile() as spool:
            with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as compressed:
                reader = _BoundedInflater(
                    stream=compressed,
                    output=spool,
                    vendor=vendor,
                    limits=limits,
                    compressed_bytes=len(payload),
                )
                # No member cache or eager metadata/body read. The TarInfo hook
                # runs before tarfile consumes a PAX/GNU payload.
                with open_archive(
                    fileobj=reader,
                    mode="r|",
                    stream=True,
                    tarinfo=_tarinfo_type(vendor=vendor, limits=limits),
                ) as archive:
                    while (member := archive.next()) is not None:
                        if member.size > limits.member_bytes or member.size < 0:
                            fail_limit(
                                vendor=vendor,
                                path=member.name,
                                limit="memberBytes",
                                maximum=limits.member_bytes,
                            )
                        normalized_mode(
                            mode=member.mode, vendor=vendor, path=member.name
                        )
                        if member.sparse is not None:
                            raise ValueError(
                                safe_diagnostic(
                                    f"vendor {vendor}: {member.name}: "
                                    "sparse archive member rejected"
                                )
                            )
                        rewrite_tarball_member(member=member)
                # Tar EOF does not imply gzip EOF. Bound padding and trailing
                # members too, rather than letting a trailing bomb escape checks.
                while reader.read(CHUNK_BYTES):
                    pass
            spool.seek(0)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(
                prefix="ai-skills-extract-", dir=dest.parent
            ) as temporary:
                staged = Path(temporary) / "tree"
                staged.mkdir()
                with open_archive(
                    fileobj=spool,
                    mode="r:",
                    stream=True,
                    tarinfo=_tarinfo_type(vendor=vendor, limits=limits),
                ) as archive:
                    while (member := archive.next()) is not None:
                        rewritten = rewrite_tarball_member(member=member)
                        if rewritten is not None:
                            if rewritten.isfile():
                                rewritten.mode = normalized_mode(
                                    mode=rewritten.mode,
                                    vendor=vendor,
                                    path=rewritten.name,
                                )
                            archive.extract(
                                member=rewritten, path=staged, filter="data"
                            )
                if dest.exists(follow_symlinks=False):
                    install_directory(source=staged, destination=dest)
                else:
                    staged.rename(dest)
    except (OSError, EOFError, tarfile.TarError) as error:
        raise RuntimeError(
            safe_diagnostic(
                f"vendor {vendor}: <archive>: could not extract vendor tarball "
                f"({type(error).__name__})"
            )
        ) from error


def rewrite_tarball_member(*, member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Strip the GitHub root prefix and reject path escapes.

    Args:
        member: Archive member as stored by GitHub.

    Returns:
        The member with a dest-relative name, or ``None`` to skip the
        top-level directory itself.

    Raises:
        ValueError: If the member path is absolute or contains ``..``.
    """
    if (
        member.name.startswith("/")
        or "\\" in member.name
        or ".." in member.name.split("/")
    ):
        raise ValueError(safe_diagnostic(f"path escape rejected: {member.name}"))
    parts = PurePosixPath(member.name).parts
    if len(parts) < 2:
        return None
    relative = PurePosixPath(*parts[1:])
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        msg = f"path escape rejected: {member.name}"
        raise ValueError(msg)
    member.name = relative.as_posix()
    return member
