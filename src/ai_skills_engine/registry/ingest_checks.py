"""Bound untrusted payload work and detect accidental LFS/secret publication.

These versioned tripwires do not establish trust. Diagnostics contain locations
and rule IDs only, never matched bytes. Vendor code is never evaluated.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import fields
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from ai_skills_engine.manifest.codec import field_key
from ai_skills_engine.registry.ingest_allow import IngestAllow
from ai_skills_engine.registry.ingest_limits import IngestLimits

RULESET_VERSION = "1"
# Lengths describe provider shapes, not validity. Test samples are synthetic.
SECRET_RULES = {
    "pem-private-key": rb"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----",
    "aws-access-key-id": rb"\bAKIA[A-Z0-9]{16}\b",
    "github-token": (
        rb"\b(?:gh[pousr]_[A-Za-z0-9]{36}|" rb"github_pat_[A-Za-z0-9_]{22,255})\b"
    ),
    "slack-token": rb"\bxox[abprs]-[A-Za-z0-9-]{10,255}\b",
    "google-api-key": rb"\bAIza[A-Za-z0-9_-]{35}\b",
    "npm-token": rb"\bnpm_[A-Za-z0-9]{36}\b",
    "stripe-live-key": rb"\bsk_live_[A-Za-z0-9]{24,255}\b",
    "anthropic-api-key": rb"\bsk-ant-[A-Za-z0-9_-]{20,255}\b",
    "openai-project-key": rb"\bsk-proj-[A-Za-z0-9_-]{20,255}\b",
}
_RULES = {name: re.compile(pattern) for name, pattern in SECRET_RULES.items()}
_LFS = re.compile(
    rb"\Aversion https://git-lfs.github.com/spec/v1\r?\n"
    rb"(?:ext-[^\r\n]+\r?\n)*oid sha256:[0-9a-f]{64}\r?\nsize [0-9]+(?:\r?\n|\Z)",
)
_PEM_END = re.compile(rb"-----END (?:[A-Z0-9]+ )?PRIVATE KEY-----")
_SPECIAL_BITS = stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX
CHUNK_BYTES = 64 * 1024


def safe_diagnostic(text: str) -> str:
    """Redact recognized secret shapes in untrusted diagnostic context.

    Args:
        text: Path, reason or upstream error text.

    Returns:
        UTF-8 text with matched values replaced, including in reasons.
    """
    data = text.encode("utf-8", errors="replace")
    # A reason can include an entire PEM example. Redacting just BEGIN would
    # leave its private material in the report. Advance monotonically so many
    # unterminated headers cannot trigger quadratic footer searches.
    position = 0
    parts: list[bytes] = []
    header_pattern = _RULES["pem-private-key"]
    while (header := header_pattern.search(data, position)) is not None:
        parts.extend((data[position : header.start()], b"[REDACTED]"))
        footer = _PEM_END.search(data, header.end())
        if footer is None:
            # A truncated block has no safe trailing boundary: withhold the
            # header and all remaining private material, then stop scanning.
            position = len(data)
            break
        position = footer.end()
    parts.append(data[position:])
    data = b"".join(parts)
    for pattern in _RULES.values():
        data = pattern.sub(b"[REDACTED]", data)
    return data.decode("utf-8", errors="replace")


def fail_limit(*, vendor: str, path: str, limit: str, maximum: int) -> None:
    """Raise a privacy-preserving, contextual limit error.

    Args:
        vendor: Consumer vendor alias.
        path: Download, archive member or selected file location.
        limit: Stable limit name.
        maximum: Effective maximum.

    Raises:
        ValueError: Always.
    """
    raise ValueError(
        safe_diagnostic(f"vendor {vendor}: {path}: {limit} limit exceeded ({maximum})"),
    )


def parse_limits(value: object, *, label: str) -> IngestLimits:
    """Strictly parse finite overrides, requiring a nonempty reason.

    Args:
        value: Raw consumer-owned mapping.
        label: Context without input values.

    Returns:
        Effective limits with defaults filled in.

    Raises:
        ValueError: On unknown keys, booleans, nonpositive limits or no reason.
    """
    names = {
        field_key(item.name): item.name
        for item in fields(IngestLimits)
        if item.name not in {"extensions", "reason"}
    }
    if (
        not isinstance(value, dict)
        or set(value) - {*names, "reason"}
        or not isinstance(value.get("reason"), str)
        or not value["reason"].strip()
        or not (set(value) & set(names))
        or any(
            type(value[key]) is not int or value[key] <= 0
            for key in value
            if key in names
        )
    ):
        raise ValueError(f"{label}: ingestLimits needs positive integers and a reason")
    return IngestLimits(
        **{names[key]: item for key, item in value.items() if key in names},
        reason=value["reason"],
    )


def parse_allow(value: object, *, label: str) -> tuple[IngestAllow, ...]:
    """Strictly parse digest acknowledgements without echoing their contents.

    Args:
        value: Raw consumer-owned acknowledgement list.
        label: Context without input values.

    Returns:
        Unique acknowledgements.

    Raises:
        ValueError: On invalid paths, digests, rules, reasons or duplicates.
    """
    if not isinstance(value, list):
        raise TypeError(f"{label}: ingestAllow must be a list")
    result: list[IngestAllow] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "rule", "sha256", "reason"}
            or any(
                not isinstance(part, str) or not part.strip() for part in item.values()
            )
        ):
            raise ValueError(f"{label}: invalid ingestAllow entry")
        path = item["path"]
        if (
            PurePosixPath(path).is_absolute()
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or "\\" in path
            or "\x00" in path
            or item["rule"] not in _RULES
            or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
            or (path, item["rule"]) in seen
        ):
            raise ValueError(
                f"{label}: invalid or duplicate ingestAllow path/rule/digest"
            )
        seen.add((path, item["rule"]))
        result.append(IngestAllow(**item))
    return tuple(result)


def normalized_mode(*, mode: int, vendor: str, path: str) -> int:
    """Reject special bits and return Git-like owner-execute permissions.

    Args:
        mode: Original permission bits before tar data filtering.
        vendor: Vendor alias.
        path: Original location.

    Returns:
        0755 for owner-executable files, otherwise 0644.

    Raises:
        ValueError: On setuid, setgid or sticky bits.
    """
    if mode & _SPECIAL_BITS:
        raise ValueError(
            safe_diagnostic(f"vendor {vendor}: {path}: special mode bits rejected")
        )
    return 0o755 if mode & stat.S_IXUSR else 0o644


def read_bounded(*, path: Path, vendor: str, limits: IngestLimits) -> bytes:
    """Bound before allocation and while reading a regular, non-symlink file.

    Args:
        path: Selected source file.
        vendor: Vendor alias.
        limits: Effective limits.

    Returns:
        Bounded file bytes.

    Raises:
        ValueError: On unsafe mode/type or file size overflow.
    """
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(
                safe_diagnostic(
                    f"vendor {vendor}: {path}: unsupported file type rejected"
                )
            )
        normalized_mode(mode=info.st_mode, vendor=vendor, path=str(path))
        if info.st_size > limits.file_bytes:
            fail_limit(
                vendor=vendor,
                path=str(path),
                limit="fileBytes",
                maximum=limits.file_bytes,
            )
        data = read_stream(
            stream=stream,
            vendor=vendor,
            path=str(path),
            maximum=limits.file_bytes,
            limit="fileBytes",
        )
        if _LFS.match(data):
            raise ValueError(
                safe_diagnostic(
                    f"vendor {vendor}: {path}: stored in Git LFS; "
                    "archive contains the pointer, not the content"
                )
            )
        return data


def read_stream(
    *, stream: BinaryIO, vendor: str, path: str, maximum: int, limit: str
) -> bytes:
    """Read at most a cap plus one sentinel byte using bounded requests.

    Args:
        stream: Readable binary stream.
        vendor: Vendor alias.
        path: Source location.
        maximum: Byte cap.
        limit: Limit identifier.

    Returns:
        Bounded bytes.

    Raises:
        ValueError: At the first byte over the cap.
    """
    data = bytearray()
    while True:
        chunk = stream.read(min(CHUNK_BYTES, maximum - len(data) + 1))
        if not chunk:
            return bytes(data)
        if len(data) + len(chunk) > maximum:
            fail_limit(vendor=vendor, path=path, limit=limit, maximum=maximum)
        data.extend(chunk)


def inspect_bytes(
    *, data: bytes, path: str, vendor: str, allow: tuple[IngestAllow, ...]
) -> list[dict[str, object]]:
    """Detect LFS and text secret shapes against original-path acknowledgements.

    Args:
        data: Already bounded bytes.
        path: Original repository-relative path, including after baking.
        vendor: Vendor alias.
        allow: Consumer-owned acknowledgements, never lock-owned.

    Returns:
        Acknowledged location/rule/digest findings without matched values.

    Raises:
        ValueError: On an LFS pointer or unacknowledged secret shape.
    """
    location = safe_diagnostic(f"vendor {vendor}: {path}")
    if _LFS.match(data):
        raise ValueError(
            f"{location}: stored in Git LFS; "
            "archive contains the pointer, not the content"
        )
    if b"\0" in data[:8192]:
        return []
    digest = hashlib.sha256(data).hexdigest()
    findings: list[dict[str, object]] = []
    acknowledgements = {
        (entry.path, entry.rule, entry.sha256): entry for entry in allow
    }
    for rule, pattern in _RULES.items():
        # One digest-bound acknowledgement covers a file/rule. Record its first
        # location; never accumulate a dict per repeated match or rescan every
        # preceding newline for every match in attacker-controlled content.
        match = pattern.search(data)
        if match is None:
            continue
        line = data.count(b"\n", 0, match.start()) + 1
        acknowledgement = acknowledgements.get((path, rule, digest))
        if acknowledgement is None:
            raise ValueError(f"{location}:{line}: {rule}: unacknowledged secret shape")
        findings.append(
            {
                "path": safe_diagnostic(path),
                "line": line,
                "rule": rule,
                "sha256": digest,
                "reason": safe_diagnostic(acknowledgement.reason),
            }
        )
    return findings


def scan_paths(
    *,
    paths: Iterable[tuple[Path, str]],
    vendor: str,
    limits: IngestLimits,
    allow: tuple[IngestAllow, ...] = (),
) -> list[dict[str, object]]:
    """Scan selected files, bounding aggregate bytes before file allocations.

    Args:
        paths: File and original repository-relative location pairs.
        vendor: Vendor alias.
        limits: Effective limits.
        allow: Consumer-owned acknowledgements.

    Returns:
        Acknowledged findings in traversal order.

    Raises:
        ValueError: At the first size, mode, LFS or content failure.
    """
    total = 0
    findings: list[dict[str, object]] = []
    allow_by_path: dict[str, list[IngestAllow]] = defaultdict(list)
    for entry in allow:
        allow_by_path[entry.path].append(entry)
    for count, (path, relative) in enumerate(paths, start=1):
        if count > limits.archive_members:
            fail_limit(
                vendor=vendor,
                path=relative,
                limit="archiveMembers",
                maximum=limits.archive_members,
            )
        size = path.stat(follow_symlinks=False).st_size
        if total + size > limits.plugin_bytes:
            fail_limit(
                vendor=vendor,
                path=relative,
                limit="pluginBytes",
                maximum=limits.plugin_bytes,
            )
        data = read_bounded(path=path, vendor=vendor, limits=limits)
        total += len(data)
        if total > limits.plugin_bytes:
            fail_limit(
                vendor=vendor,
                path=relative,
                limit="pluginBytes",
                maximum=limits.plugin_bytes,
            )
        findings.extend(
            inspect_bytes(
                data=data,
                path=relative,
                vendor=vendor,
                allow=tuple(allow_by_path.get(relative, ())),
            )
        )
    return findings


def limits_record(limits: IngestLimits) -> dict[str, object]:
    """Serialize effective limits, redacting any secret-shaped reason.

    Args:
        limits: Effective consumer policy.

    Returns:
        JSON-compatible effective policy.
    """
    return {
        field_key(item.name): (
            safe_diagnostic(value)
            if isinstance(value := getattr(limits, item.name), str)
            else value
        )
        for item in fields(limits)
        if item.name != "extensions"
    }


def validate_input_tree(*, root: Path, vendor: str, limits: IngestLimits) -> None:
    """Bound an offline snapshot before sorted walks or other tree allocations.

    Content checks remain restricted to selected files. This structural pass
    counts directories/links as archive members and bounds regular file sizes.
    Symlink policy remains the existing role-specific bake/inventory decision.

    Args:
        root: Explicit vendor tree.
        vendor: Consumer alias.
        limits: Effective archive policy.

    Raises:
        ValueError: On a structural limit or unsupported node/mode.
    """
    count = 0
    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        info = current.stat(follow_symlinks=False)
        normalized_mode(mode=info.st_mode, vendor=vendor, path=str(current))
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(
                safe_diagnostic(f"vendor {vendor}: {current}: unsafe tree root")
            )
        with os.scandir(current) as entries:
            for entry in entries:
                count += 1
                relative = Path(entry.path).relative_to(root).as_posix()
                if count > limits.archive_members:
                    fail_limit(
                        vendor=vendor,
                        path=relative,
                        limit="archiveMembers",
                        maximum=limits.archive_members,
                    )
                info = entry.stat(follow_symlinks=False)
                normalized_mode(mode=info.st_mode, vendor=vendor, path=relative)
                if stat.S_ISDIR(info.st_mode):
                    stack.append(Path(entry.path))
                elif stat.S_ISREG(info.st_mode):
                    total += info.st_size
                    for key, actual, maximum in (
                        ("memberBytes", info.st_size, limits.member_bytes),
                        ("archiveBytes", total, limits.archive_bytes),
                    ):
                        if actual > maximum:
                            fail_limit(
                                vendor=vendor, path=relative, limit=key, maximum=maximum
                            )
                elif not stat.S_ISLNK(info.st_mode):
                    raise ValueError(
                        safe_diagnostic(
                            f"vendor {vendor}: {relative}: "
                            "unsupported file type rejected"
                        )
                    )
