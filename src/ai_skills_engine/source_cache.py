"""Content-addressed cache of canonical vendor source trees, verified on every read.

Layout below ``${AI_SKILLS_CACHE:-${XDG_CACHE_HOME:-~/.cache}/ai-skills}``:

- ``sources/sha256-<hex>.tar``: canonical uncompressed tar of one extracted tree.
- ``refs/<owner>/<repo>/<revision>``: the ``sha256:<hex>`` source digest of that pin.

A source digest is the SHA-256 of the canonical tar, which is a pure function of
the extracted tree (sorted PAX entries, normalized modes, no owners or times). It
therefore never depends on how a forge compresses its archive. All writes go
through :func:`ai_skills_engine.atomic_write.atomic_write`; nothing from a vendor
tree is executed.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import tarfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from ai_skills_engine.atomic_write import atomic_write
from ai_skills_engine.registry.ingest_checks import (
    normalized_mode,
    safe_diagnostic,
    validate_input_tree,
)
from ai_skills_engine.registry.vendor import Vendor

CACHE_ENV = "AI_SKILLS_CACHE"
FETCH_HINT = "run `ai-skills-engine lock --fetch`"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_SEGMENT = re.compile(r"[A-Za-z0-9_.-]+")
_REVISION = re.compile(r"[0-9a-f]{40}")
type Fetcher = Callable[..., None]


class SourceCacheError(RuntimeError):
    """Base class for actionable source cache failures."""


class CacheMissError(SourceCacheError):
    """A frozen operation needs a source that is not cached."""


class CacheCorruptError(SourceCacheError):
    """A cache entry no longer matches its content address."""


class SourceMismatchError(SourceCacheError):
    """Acquired bytes disagree with the digest recorded in the lock."""


def cache_root(environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the cache root from the documented environment variables.

    Args:
        environ: Environment mapping, defaulting to the process environment.

    Returns:
        ``$AI_SKILLS_CACHE``, else ``$XDG_CACHE_HOME/ai-skills`` for an absolute
        XDG value, else ``~/.cache/ai-skills``.
    """
    env = os.environ if environ is None else environ
    explicit = env.get(CACHE_ENV, "")
    if explicit:
        return Path(explicit).expanduser()
    xdg = env.get("XDG_CACHE_HOME", "")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".cache"
    return base / "ai-skills"


def digest_bytes(data: bytes) -> str:
    """Hash bytes with an explicit algorithm prefix.

    Args:
        data: Exact bytes.

    Returns:
        Qualified SHA-256 digest.
    """
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_source_tar(*, root: Path, vendor: str) -> bytes:
    """Encode an extracted source tree as deterministic uncompressed tar bytes.

    Entries are sorted PAX records for every directory, regular file and symbolic
    link below ``root``. Files use Git-like 0644/0755 modes; uid, gid and mtime
    are zero and owner names empty. Link targets are stored verbatim; the
    existing role-specific symlink policy still decides whether they are usable.

    Args:
        root: Validated source tree.
        vendor: Consumer alias for diagnostics.

    Returns:
        Canonical tar bytes whose SHA-256 is the source digest.

    Raises:
        ValueError: On special mode bits or unsupported node types.
    """
    nodes: list[tuple[str, Path, os.stat_result]] = []
    stack = [root]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                path = Path(entry.path)
                info = path.lstat()
                nodes.append((path.relative_to(root).as_posix(), path, info))
                if stat.S_ISDIR(info.st_mode):
                    stack.append(path)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, path, info in sorted(nodes, key=lambda item: item[0]):
            mode = normalized_mode(mode=info.st_mode, vendor=vendor, path=name)
            header = tarfile.TarInfo(name)
            header.uid = header.gid = header.mtime = 0
            header.uname = header.gname = ""
            if stat.S_ISDIR(info.st_mode):
                header.type = tarfile.DIRTYPE
                header.mode = 0o755
                archive.addfile(header)
            elif stat.S_ISLNK(info.st_mode):
                header.type = tarfile.SYMTYPE
                header.mode = 0o777
                header.linkname = os.readlink(path)
                archive.addfile(header)
            elif stat.S_ISREG(info.st_mode):
                data = path.read_bytes()
                header.mode = mode
                header.size = len(data)
                archive.addfile(header, io.BytesIO(data))
            else:
                raise ValueError(
                    safe_diagnostic(
                        f"vendor {vendor}: {name}: unsupported file type rejected"
                    )
                )
    return output.getvalue()


def extract_canonical(*, data: bytes, dest: Path) -> None:
    """Recreate a canonical source tree without writing through any link.

    Every member's parent must be a directory created earlier from the same
    archive, so a symbolic link can never redirect a later write.

    Args:
        data: Digest-verified canonical tar bytes.
        dest: New directory to create.

    Raises:
        CacheCorruptError: On a member that canonical encoding cannot produce.
    """
    dest.mkdir(parents=True)
    directories = {""}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive:
            name = member.name
            parts = name.split("/")
            parent = "/".join(parts[:-1])
            if (
                any(part in {"", ".", ".."} for part in parts)
                or PurePosixPath(name).is_absolute()
                or parent not in directories
                or name in directories
            ):
                raise CacheCorruptError(f"Unsafe cached source member: {name!r}")
            target = dest.joinpath(*parts)
            if member.isdir():
                target.mkdir()
                directories.add(name)
            elif member.issym():
                os.symlink(member.linkname, target)
            elif member.isreg():
                stream = archive.extractfile(member)
                if stream is None:
                    raise CacheCorruptError(f"Missing cached source payload: {name!r}")
                mode = 0o755 if member.mode & stat.S_IXUSR else 0o644
                descriptor = os.open(
                    target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode
                )
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(stream.read())
                    os.fchmod(handle.fileno(), mode)
            else:
                raise CacheCorruptError(f"Unsupported cached source member: {name!r}")


@dataclass(frozen=True)
class SourceCache:
    """Content-addressed source storage rooted at one directory.

    Attributes:
        root: Cache root directory.
    """

    root: Path

    @classmethod
    def default(cls) -> SourceCache:
        """Open the cache selected by the process environment.

        Returns:
            Cache at :func:`cache_root`.
        """
        return cls(root=cache_root())

    def source_path(self, digest: str) -> Path:
        """Locate the canonical tar for a source digest.

        Args:
            digest: Qualified ``sha256:<hex>`` digest.

        Returns:
            Content-addressed path.

        Raises:
            ValueError: For a malformed digest.
        """
        if _DIGEST.fullmatch(digest) is None:
            raise ValueError(f"Invalid source digest: {digest!r}")
        return self.root / "sources" / ("sha256-" + digest[7:] + ".tar")

    def ref_path(self, *, repo: str, revision: str) -> Path:
        """Locate the revision index entry for a pinned repository.

        Args:
            repo: ``owner/name`` repository.
            revision: 40-hex commit SHA.

        Returns:
            Path of the ref file.

        Raises:
            ValueError: For a malformed repository or revision.
        """
        segments = repo.split("/")
        if (
            len(segments) != 2
            or any(
                _SEGMENT.fullmatch(item) is None or item in {".", ".."}
                for item in segments
            )
            or _REVISION.fullmatch(revision) is None
        ):
            raise ValueError(f"Invalid pinned source coordinate: {repo}@{revision}")
        return self.root / "refs" / segments[0] / segments[1] / revision

    def has(self, digest: str) -> bool:
        """Report whether a source entry exists, without trusting its bytes.

        Args:
            digest: Qualified source digest.

        Returns:
            Whether a regular file is stored at the content address.
        """
        path = self.source_path(digest)
        return path.is_file() and not path.is_symlink()

    def read(self, digest: str, *, label: str) -> bytes:
        """Read and re-verify one source entry.

        Args:
            digest: Qualified source digest.
            label: Vendor alias for diagnostics.

        Returns:
            Verified canonical tar bytes.

        Raises:
            CacheMissError: If the entry is absent.
            CacheCorruptError: If the stored bytes no longer match the digest.
        """
        path = self.source_path(digest)
        if not self.has(digest):
            raise CacheMissError(
                f"Source cache miss for vendor {label} ({digest}) in {self.root}; "
                + FETCH_HINT
            )
        data = path.read_bytes()
        actual = digest_bytes(data)
        if actual != digest:
            raise CacheCorruptError(
                f"Corrupted source cache entry for vendor {label}: {path.name} "
                f"hashes to {actual}, expected {digest}; delete it and " + FETCH_HINT
            )
        return data

    def lookup(self, *, repo: str, revision: str) -> str | None:
        """Resolve a pinned revision through the refs index.

        Args:
            repo: ``owner/name`` repository.
            revision: 40-hex commit SHA.

        Returns:
            Recorded source digest, or None when the revision is not indexed.

        Raises:
            CacheCorruptError: If the ref entry is malformed.
        """
        path = self.ref_path(repo=repo, revision=revision)
        if not path.is_file():
            return None
        value = path.read_bytes().decode("utf-8", errors="replace").strip()
        if _DIGEST.fullmatch(value) is None:
            raise CacheCorruptError(
                f"Corrupted source cache ref for {repo}@{revision}; delete "
                f"{path} and " + FETCH_HINT
            )
        return value

    def store(
        self, *, data: bytes, repo: str, revision: str, label: str, expected: str | None
    ) -> str:
        """Publish canonical bytes and their ref, verifying a locked digest first.

        Args:
            data: Canonical source tar bytes.
            repo: ``owner/name`` repository.
            revision: 40-hex commit SHA.
            label: Vendor alias for diagnostics.
            expected: Locked digest that the bytes must match, if any.

        Returns:
            Stored source digest.

        Raises:
            SourceMismatchError: If ``expected`` differs; nothing is written.
        """
        digest = digest_bytes(data)
        if expected is not None and digest != expected:
            raise SourceMismatchError(
                f"Source bytes for vendor {label} ({repo}@{revision}) have "
                f"sourceDigest {digest}, but ai-skills.lock records {expected}"
            )
        path = self.source_path(digest)
        if not self.has(digest) or digest_bytes(path.read_bytes()) != digest:
            atomic_write(path=path, data=data)
        atomic_write(
            path=self.ref_path(repo=repo, revision=revision),
            data=(digest + "\n").encode(),
        )
        return digest

    def extract(self, digest: str, *, dest: Path, label: str) -> None:
        """Materialize a verified cached source into a new directory.

        Args:
            digest: Qualified source digest.
            dest: New directory to create.
            label: Vendor alias for diagnostics.
        """
        extract_canonical(data=self.read(digest, label=label), dest=dest)


def canonical_snapshot(*, tree: Path, vendor: Vendor) -> bytes:
    """Validate an acquired or supplied tree, then encode it canonically.

    Args:
        tree: Acquired or caller-supplied source tree.
        vendor: Pin whose ingestion limits apply.

    Returns:
        Canonical source tar bytes.
    """
    validate_input_tree(root=tree, vendor=vendor.id, limits=vendor.ingest_limits)
    return canonical_source_tar(root=tree, vendor=vendor.id)


def materialize(
    *,
    cache: SourceCache,
    vendor: Vendor,
    dest: Path,
    fetcher: Fetcher | None,
    expected: str | None = None,
) -> str:
    """Materialize a pinned source from the cache, acquiring it only on a miss.

    Acquired trees pass the existing structural ingestion checks before they
    are stored. Both cold and warm paths extract the same canonical bytes, so
    every consumer observes an identical tree.

    Args:
        cache: Source cache.
        vendor: Pin (``repo``/``sha``) and ingestion limits.
        dest: New directory to create.
        fetcher: Keyword ``(vendor=, dest=)`` acquisition function; None
            forbids acquisition (frozen, offline operation).
        expected: Locked source digest the materialized tree must have.

    Returns:
        Source digest of the materialized tree.

    Raises:
        CacheMissError: When the source is absent and acquisition is forbidden.
    """
    digest = expected or cache.lookup(repo=vendor.repo, revision=vendor.sha)
    if digest is not None and cache.has(digest):
        cache.extract(digest, dest=dest, label=vendor.id)
        return digest
    if fetcher is None:
        raise CacheMissError(
            f"Source cache miss for vendor {vendor.id} ({vendor.repo}@{vendor.sha})"
            f" in {cache.root}; " + FETCH_HINT
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".ai-skills-fetch-", dir=dest.parent) as scratch:
        tree = Path(scratch) / "tree"
        fetcher(vendor=vendor, dest=tree)
        data = canonical_snapshot(tree=tree, vendor=vendor)
    digest = cache.store(
        data=data,
        repo=vendor.repo,
        revision=vendor.sha,
        label=vendor.id,
        expected=expected,
    )
    extract_canonical(data=data, dest=dest)
    return digest
