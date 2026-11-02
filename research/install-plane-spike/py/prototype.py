"""Throwaway, stdlib-only resolved-artifact installer; never resolves or fetches."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

LIMIT = 1024 * 1024
PATH_LIMIT = 100  # ASCII bytes/characters; fits the tiny USTAR name field.
PATH_DEPTH = 16
JSON_DEPTH = 64
PATH_PATTERN = re.compile(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)+")
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
DEVICE_PATTERN = re.compile(
    r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", re.IGNORECASE
)


def validate_header(header: bytes) -> int:
    """Reject ambiguous fields outside the shared tiny USTAR profile.

    Args:
        header: One raw 512-byte regular-file header.

    Returns:
        Regular-file payload size from the validated raw header.

    Raises:
        ValueError: For unsupported types, ambiguous fields or invalid checksums.
    """
    if (
        header[156:157] not in {tarfile.REGTYPE, tarfile.AREGTYPE}
        or header[257:263] != b"ustar\0"
        or any(header[345:512])
    ):
        raise ValueError("invalid archive inventory")
    if any(byte >= 0x80 for byte in header):
        raise ValueError("non-ASCII archive header")
    for start, end in ((0, 100), (157, 257), (265, 297), (297, 329)):
        field = header[start:end]
        if b"\0" in field and any(field[field.index(0) :]):
            raise ValueError("nonzero bytes after archive string terminator")
    # Empty numbers, including size, are rejected rather than coerced to zero.
    for start, end in (
        (100, 108),
        (108, 116),
        (116, 124),
        (124, 136),
        (136, 148),
        (148, 156),
    ):
        if not re.fullmatch(rb" *[0-7]+[ \0]*", header[start:end]):
            raise ValueError("invalid archive number")
    checksum = sum(header[:148]) + 8 * 32 + sum(header[156:])
    if checksum != int(header[148:156].rstrip(b" \0"), 8):
        raise ValueError("invalid archive checksum")
    return int(header[124:136].rstrip(b" \0"), 8)


def validate_archive(archive: bytes) -> None:
    """Validate every raw header before tarfile can consume extension records.

    Args:
        archive: Already bounded and digest-verified fixture bytes.

    Raises:
        ValueError: If headers, payload bounds or the zero trailer are invalid.
    """
    if len(archive) % 512:
        raise ValueError("invalid archive length")
    offset = 0
    while offset + 512 <= len(archive):
        header = archive[offset : offset + 512]
        if not any(header):
            if len(archive) - offset < 1024 or any(archive[offset:]):
                raise ValueError("invalid archive trailer")
            return
        size = validate_header(header)
        if offset + 512 + size > len(archive):
            raise ValueError("invalid archive inventory")
        offset += 512 + ((size + 511) // 512) * 512
    raise ValueError("incomplete archive")


def safe_path(value: object) -> str:
    """Validate the small fixture's portable file-path profile.

    Args:
        value: Untrusted archive or index path.

    Returns:
        Validated relative POSIX path.

    Raises:
        ValueError: If the path is outside the spike profile.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("invalid path")
    # Check budgets before regex, split, or allocating any directory prefixes.
    if len(value) > PATH_LIMIT:
        raise ValueError("path length limit")
    if value.count("/") >= PATH_DEPTH:
        raise ValueError("path depth limit")
    if not PATH_PATTERN.fullmatch(value) or any(
        part in {".", ".."} or part.endswith(".") or DEVICE_PATTERN.fullmatch(part)
        for part in value.split("/")
    ):
        raise ValueError("invalid path")
    return value


def parse_index(raw: str) -> object:
    """Reject excessive nesting and duplicate decoded keys before interpretation.

    Args:
        raw: Size-bounded UTF-8 index text.

    Returns:
        Parsed JSON with unique keys in every object.

    Raises:
        ValueError: On malformed JSON, duplicate keys or excessive nesting.
    """
    depth, quoted, escaped = 0, False, False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > JSON_DEPTH:
                raise ValueError("index nesting too deep")
        elif char in "]}":
            depth -= 1

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        """Reject repeated decoded object names instead of losing earlier values."""
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate index key")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=unique)
    except RecursionError as error:
        raise ValueError("index nesting too deep") from error


def install(*, fixture: Path, home: Path, exclude: str) -> dict[str, str]:
    """Validate the complete artifact before materializing retained files.

    Args:
        fixture: Directory containing index.json and artifact.tar.
        home: Disposable HOME, whose .spike-target must not exist.
        exclude: One known capability ID to subtract.

    Returns:
        Retained path to UTF-8 contents, for golden-fixture comparison.

    Raises:
        ValueError: On digest, inventory, path, or closure violations.
        OSError: If inputs or the destination cannot be used.
    """
    index_bytes = read_fixture(fixture / "index.json")
    archive = read_fixture(fixture / "artifact.tar")
    index = parse_index(index_bytes.decode("utf-8"))
    if not isinstance(index, dict) or set(index) != {"sha256", "capabilities"}:
        raise ValueError("invalid index")
    if hashlib.sha256(archive).hexdigest() != index["sha256"]:
        raise ValueError("archive digest mismatch")
    capabilities = index["capabilities"]
    if not isinstance(capabilities, list) or not capabilities:
        raise ValueError("missing capabilities")
    ids: set[str] = set()
    files: dict[str, str] = {}
    retained: set[str] = set()
    for capability in capabilities:
        if not isinstance(capability, dict) or set(capability) != {
            "id",
            "closure",
            "files",
        }:
            raise ValueError("invalid capability")
        identity = capability["id"]
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError("invalid capability id")
        ids.add(identity)
        closure = capability["closure"]
        if not isinstance(closure, list) or any(
            not isinstance(x, str) for x in closure
        ):
            raise ValueError("missing closure")
        if not isinstance(capability["files"], dict) or not capability["files"]:
            raise ValueError("missing files")
        for name, digest in capability["files"].items():
            safe_path(name)
            if (
                name in files
                or not isinstance(digest, str)
                or not HASH_PATTERN.fullmatch(digest)
            ):
                raise ValueError("invalid file inventory")
            files[name] = digest
            if identity != exclude:
                retained.add(name)
    if exclude not in ids:
        raise ValueError("unknown exclusion")
    # Include excluded files and directory components: all names must represent
    # distinct portable filesystem identities before any destination is created.
    identities: dict[str, str] = {}
    for name in files:
        parts = name.split("/")
        for count in range(1, len(parts) + 1):
            path = "/".join(parts[:count])
            key = path.lower()
            kind = "file" if count == len(parts) else "directory"
            identity = f"{kind}:{path}"
            if key in identities and identities[key] != identity:
                raise ValueError("portable path collision")
            identities[key] = identity
    for capability in capabilities:
        closure = capability["closure"]
        if len(set(closure)) != len(closure) or not set(closure) <= ids:
            raise ValueError("invalid closure")
        if capability["id"] != exclude and exclude in closure:
            raise ValueError("retained closure contains exclusion")

    contents: dict[str, str] = {}
    validate_archive(archive)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        for member in tar:
            name = safe_path(member.name)
            if (
                member.type not in {tarfile.REGTYPE, tarfile.AREGTYPE}
                or member.pax_headers
                or name not in files
                or name in contents
            ):
                raise ValueError("invalid archive inventory")
            stream = tar.extractfile(member)
            if stream is None:
                raise ValueError("missing file bytes")
            payload = stream.read(LIMIT + 1)
            if hashlib.sha256(payload).hexdigest() != files[name]:
                raise ValueError("file digest mismatch")
            contents[name] = payload.decode("utf-8")
        trailer = archive[tar.offset :]
        if len(trailer) < 1024 or any(trailer):
            raise ValueError("invalid archive trailer")
    if set(contents) != set(files):
        raise ValueError("incomplete archive")
    output = {name: contents[name] for name in sorted(retained)}
    target = home / ".spike-target"
    temporary = tempfile.TemporaryDirectory(prefix=".spike-stage-", dir=home)
    staging = Path(temporary.name)
    owns_target = False
    is_published = False
    failures: list[Exception] = []
    try:
        for name, content in output.items():
            destination = staging / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content.encode("utf-8"))
        # Reserve a fresh target without replacing any existing file, link or
        # directory. Only publish after all writes succeed. Move failures roll
        # back only this invocation's reservation, never a pre-existing target.
        target.mkdir()
        owns_target = True
        for child in staging.iterdir():
            child.rename(target / child.name)
        is_published = True
    except (OSError, ValueError, RuntimeError, TypeError) as error:
        failures.append(error)
        if owns_target:
            try:
                shutil.rmtree(target)
            except OSError as cleanup_error:
                failures.append(cleanup_error)
    try:
        temporary.cleanup()
    except OSError as cleanup_error:
        if is_published:
            # Publication commits the installation, as in the TypeScript variant.
            print(
                f"Installation completed; staging cleanup failed: {cleanup_error}",
                file=sys.stderr,
            )
        else:
            failures.append(cleanup_error)
    if len(failures) == 1:
        raise failures[0]
    if failures:
        details = "; ".join(str(error) for error in failures)
        raise ExceptionGroup(
            f"Installation failed; cleanup also failed: {details}", failures
        ) from failures[0]
    return output


def read_fixture(path: Path) -> bytes:
    """Bound allocation before parsing or hashing even growing input files.

    Args:
        path: Untrusted local fixture input.

    Returns:
        At most LIMIT bytes.

    Raises:
        ValueError: If the input exceeds the fixture budget.
        OSError: If the input cannot be read.
    """
    with path.open("rb") as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("fixture too large")
    return data


def main() -> int:
    """Run the fixed CLI and emit a JSON golden result.

    Returns:
        Zero on success, one on validation or I/O failure.
    """
    try:
        if len(sys.argv) != 3 or not os.environ.get("HOME"):
            raise ValueError(
                "usage: prototype FIXTURE EXCLUDE (requires disposable HOME)"
            )
        result = install(
            fixture=Path(sys.argv[1]),
            home=Path(os.environ["HOME"]),
            exclude=sys.argv[2],
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, tarfile.TarError, ExceptionGroup) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
