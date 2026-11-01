"""Throwaway, stdlib-only resolved-artifact installer; never resolves or fetches."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import tarfile
from pathlib import Path

LIMIT = 1024 * 1024
PATH_PATTERN = re.compile(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)+")
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
DEVICE_PATTERN = re.compile(
    r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", re.IGNORECASE
)


def safe_path(value: object) -> str:
    """Validate the small fixture's portable file-path profile.

    Args:
        value: Untrusted archive or index path.

    Returns:
        Validated relative POSIX path.

    Raises:
        ValueError: If the path is outside the spike profile.
    """
    if (
        not isinstance(value, str)
        or not PATH_PATTERN.fullmatch(value)
        or any(
            part in {".", ".."} or part.endswith(".") or DEVICE_PATTERN.fullmatch(part)
            for part in value.split("/")
        )
    ):
        raise ValueError("invalid path")
    return value


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
    index = json.loads(index_bytes.decode("utf-8"))
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
    if len(archive) % 512:
        raise ValueError("invalid archive length")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        for member in tar:
            name = safe_path(member.name)
            if (
                member.type not in {tarfile.REGTYPE, tarfile.AREGTYPE}
                or any(
                    byte >= 0x80
                    for byte in archive[member.offset : member.offset + 512]
                )
                or member.pax_headers
                or name not in files
                or name in contents
                or archive[member.offset + 257 : member.offset + 263] != b"ustar\0"
                or any(archive[member.offset + 345 : member.offset + 500])
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
    target.mkdir()  # A fresh disposable destination avoids overwrite/symlink traversal.
    for name, content in output.items():
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content.encode("utf-8"))
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
    except (ValueError, OSError, tarfile.TarError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
