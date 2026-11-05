"""Strict load and canonical dump of the committed ``ai-skills.lock``.

The lock is JSON with sorted keys, 2-space indentation and a trailing newline.
It never contains timestamps, absolute paths, usernames or hostnames. Reading
is strict: an unknown ``lockVersion`` or key fails with a specific message and
is never read on a best-effort basis. Machine-local install receipts are a
separate file and never mix with this lock.
"""

import json
import re
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ai_skills_engine.artifacts.format import canonical_json
from ai_skills_engine.atomic_write import atomic_write
from ai_skills_engine.lockmodel.builder import Builder
from ai_skills_engine.lockmodel.filters import Filters
from ai_skills_engine.lockmodel.lock import LOCK_VERSION, Lock
from ai_skills_engine.lockmodel.locked_capability import LockedCapability
from ai_skills_engine.lockmodel.locked_package import LockedPackage
from ai_skills_engine.lockmodel.locked_resource import LockedResource
from ai_skills_engine.lockmodel.locked_vendor import LockedVendor
from ai_skills_engine.lockmodel.manifest_record import ManifestRecord
from ai_skills_engine.provenance.ingest import schema as lineage_schema

LOCK_FILENAME = "ai-skills.lock"
LOCK_HINT = "run `ai-skills-engine lock`"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_SHA = re.compile(r"[0-9a-f]{40}")
_REPO = re.compile(r"(?!\.\.?/)[A-Za-z0-9_.-]+/(?!\.\.?$)[A-Za-z0-9_.-]+")
_ROOT_KEYS = frozenset({"lockVersion", "builder", "manifest", "vendors", "packages"})


class LockError(ValueError):
    """Base class for unreadable or unusable locks."""


class LockVersionError(LockError):
    """The lock declares a version this engine cannot read."""


class LockKeyError(LockError):
    """The lock contains a key this engine does not define."""


class LockFormatError(LockError):
    """The lock is malformed or not canonical."""


class StaleLockError(LockError):
    """The lock no longer matches the manifest, local inputs or builder."""


class MissingLockError(LockError):
    """No lock exists where one is required."""


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON object keys instead of keeping the last one.

    Args:
        pairs: Decoded object members.

    Returns:
        Mapping of the members.

    Raises:
        LockFormatError: On a duplicate key.
    """
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LockFormatError(f"{LOCK_FILENAME}: duplicate key {key!r}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    """Reject non-standard JSON numbers.

    Args:
        value: NaN or Infinity spelling.

    Raises:
        LockFormatError: Always.
    """
    raise LockFormatError(f"{LOCK_FILENAME}: invalid JSON constant {value}")


def _object(value: object, *, keys: frozenset[str], location: str) -> dict[str, Any]:
    """Require an object with exactly the defined keys.

    Args:
        value: Decoded JSON value.
        keys: Complete key set for this record.
        location: JSON pointer for diagnostics.

    Returns:
        Validated mapping.

    Raises:
        LockFormatError: For a non-object or a missing key.
        LockKeyError: For an undefined key.
    """
    if not isinstance(value, dict):
        raise LockFormatError(f"{LOCK_FILENAME}: {location or '/'} must be an object")
    unknown = sorted(set(value) - keys)
    if unknown:
        raise LockKeyError(
            f"{LOCK_FILENAME}: unknown key {unknown[0]!r} at {location or '/'}; "
            f"lockVersion {LOCK_VERSION} does not define it"
        )
    missing = sorted(keys - set(value))
    if missing:
        raise LockFormatError(
            f"{LOCK_FILENAME}: missing key {missing[0]!r} at {location or '/'}"
        )
    return value


def _string(
    value: object, *, location: str, pattern: re.Pattern[str] | None = None
) -> str:
    """Require a non-empty string, optionally matching a pattern.

    Args:
        value: Decoded JSON value.
        location: JSON pointer for diagnostics.
        pattern: Required full match.

    Returns:
        Validated string.

    Raises:
        LockFormatError: For any other value.
    """
    if (
        not isinstance(value, str)
        or not value
        or (pattern is not None and pattern.fullmatch(value) is None)
    ):
        raise LockFormatError(f"{LOCK_FILENAME}: invalid value at {location}")
    return value


def _list[T](
    value: object, *, location: str, item: Callable[[object, str], T]
) -> tuple[T, ...]:
    """Require a JSON array and parse each element.

    Args:
        value: Decoded JSON value.
        location: JSON pointer for diagnostics.
        item: Element parser receiving the element and its pointer.

    Returns:
        Parsed elements.

    Raises:
        LockFormatError: For a non-array.
    """
    if not isinstance(value, list):
        raise LockFormatError(f"{LOCK_FILENAME}: {location} must be an array")
    return tuple(
        item(element, f"{location}/{index}") for index, element in enumerate(value)
    )


@cache
def _lineage_validator() -> Draft202012Validator:
    """Build the packaged lineage schema validator once per process.

    Returns:
        Validator for one lineage chain.
    """
    return Draft202012Validator(lineage_schema())


def _lineage(value: object, location: str) -> tuple[dict[str, Any], ...]:
    """Validate lineage chains against the shipped lineage schema.

    Args:
        value: Decoded lineage array.
        location: JSON pointer for diagnostics.

    Returns:
        Validated chains.
    """
    validator = _lineage_validator()

    def chain(element: object, pointer: str) -> dict[str, Any]:
        """Validate one chain.

        Args:
            element: Decoded chain.
            pointer: JSON pointer for diagnostics.

        Returns:
            Validated chain.

        Raises:
            LockFormatError: On a schema violation.
        """
        errors = list(validator.iter_errors(element))
        if errors or not isinstance(element, dict):
            message = errors[0].message if errors else "must be an object"
            raise LockFormatError(
                f"{LOCK_FILENAME}: invalid lineage at {pointer}: {message}"
            )
        return element

    return _list(value, location=location, item=chain)


def _text(element: object, pointer: str) -> str:
    """Parse one non-empty string element.

    Args:
        element: Decoded value.
        pointer: JSON pointer for diagnostics.

    Returns:
        Validated string.
    """
    return _string(element, location=pointer)


def _vendor(value: object, location: str) -> LockedVendor:
    """Parse one vendor record.

    Args:
        value: Decoded record.
        location: JSON pointer for diagnostics.

    Returns:
        Typed vendor.
    """
    data = _object(
        value,
        keys=frozenset({"id", "repo", "sha", "sourceDigest", "filters"}),
        location=location,
    )
    filters = _object(
        data["filters"],
        keys=frozenset({"include", "exclude"}),
        location=location + "/filters",
    )
    return LockedVendor(
        id=_string(data["id"], location=location + "/id"),
        repo=_string(data["repo"], location=location + "/repo", pattern=_REPO),
        sha=_string(data["sha"], location=location + "/sha", pattern=_SHA),
        source_digest=_string(
            data["sourceDigest"], location=location + "/sourceDigest", pattern=_DIGEST
        ),
        filters=Filters(
            include=_list(
                filters["include"], location=location + "/filters/include", item=_text
            ),
            exclude=_list(
                filters["exclude"], location=location + "/filters/exclude", item=_text
            ),
        ),
    )


def _capability(value: object, location: str) -> LockedCapability:
    """Parse one capability record.

    Args:
        value: Decoded record.
        location: JSON pointer for diagnostics.

    Returns:
        Typed capability.
    """
    data = _object(
        value, keys=frozenset({"id", "closure", "lineage"}), location=location
    )
    return LockedCapability(
        id=_string(data["id"], location=location + "/id"),
        closure=_list(data["closure"], location=location + "/closure", item=_text),
        lineage=_lineage(data["lineage"], location + "/lineage"),
    )


def _resource(value: object, location: str) -> LockedResource:
    """Parse one standalone resource record.

    Args:
        value: Decoded record.
        location: JSON pointer for diagnostics.

    Returns:
        Typed resource.
    """
    data = _object(value, keys=frozenset({"id", "lineage"}), location=location)
    return LockedResource(
        id=_string(data["id"], location=location + "/id"),
        lineage=_lineage(data["lineage"], location + "/lineage"),
    )


def _package(value: object, location: str) -> LockedPackage:
    """Parse one package record.

    Args:
        value: Decoded record.
        location: JSON pointer for diagnostics.

    Returns:
        Typed package.
    """
    data = _object(
        value,
        keys=frozenset(
            {
                "id",
                "version",
                "artifactDigest",
                "treeDigest",
                "capabilities",
                "resources",
            }
        ),
        location=location,
    )
    return LockedPackage(
        id=_string(data["id"], location=location + "/id"),
        version=_string(data["version"], location=location + "/version"),
        artifact_digest=_string(
            data["artifactDigest"],
            location=location + "/artifactDigest",
            pattern=_DIGEST,
        ),
        tree_digest=_string(
            data["treeDigest"], location=location + "/treeDigest", pattern=_DIGEST
        ),
        capabilities=_list(
            data["capabilities"], location=location + "/capabilities", item=_capability
        ),
        resources=_list(
            data["resources"], location=location + "/resources", item=_resource
        ),
    )


def loads(data: bytes) -> Lock:
    """Parse lock bytes strictly.

    Args:
        data: Raw lock file bytes.

    Returns:
        Typed lock.

    Raises:
        LockFormatError: For malformed JSON or values.
        LockVersionError: For an unknown ``lockVersion``.
        LockKeyError: For an undefined key.
    """
    try:
        document = json.loads(
            data.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant
        )
    except UnicodeDecodeError as error:
        raise LockFormatError(f"{LOCK_FILENAME}: not UTF-8 text") from error
    except json.JSONDecodeError as error:
        raise LockFormatError(f"{LOCK_FILENAME}: invalid JSON ({error.msg})") from error
    if not isinstance(document, dict):
        raise LockFormatError(f"{LOCK_FILENAME}: / must be an object")
    version = document.get("lockVersion")
    if type(version) is not int or version != LOCK_VERSION:
        raise LockVersionError(
            f"{LOCK_FILENAME}: unsupported lockVersion {version!r}; this engine "
            f"reads lockVersion {LOCK_VERSION}. Use a matching engine or "
            "regenerate the lock; it is never read on a best-effort basis"
        )
    root = _object(document, keys=_ROOT_KEYS, location="")
    builder = _object(
        root["builder"],
        keys=frozenset({"engineVersion", "artifactFormat"}),
        location="/builder",
    )
    if type(builder["artifactFormat"]) is not int:
        raise LockFormatError(
            f"{LOCK_FILENAME}: invalid value at /builder/artifactFormat"
        )
    manifest = _object(
        root["manifest"],
        keys=frozenset({"apiVersion", "digest", "inputsDigest"}),
        location="/manifest",
    )
    return Lock(
        builder=Builder(
            engine_version=_string(
                builder["engineVersion"], location="/builder/engineVersion"
            ),
            artifact_format=builder["artifactFormat"],
        ),
        manifest=ManifestRecord(
            api_version=_string(
                manifest["apiVersion"], location="/manifest/apiVersion"
            ),
            digest=_string(
                manifest["digest"], location="/manifest/digest", pattern=_DIGEST
            ),
            inputs_digest=_string(
                manifest["inputsDigest"],
                location="/manifest/inputsDigest",
                pattern=_DIGEST,
            ),
        ),
        vendors=_list(root["vendors"], location="/vendors", item=_vendor),
        packages=_list(root["packages"], location="/packages", item=_package),
    )


def dumps(lock: Lock) -> bytes:
    """Encode a lock canonically.

    Args:
        lock: Typed lock.

    Returns:
        Sorted-key, 2-space indented UTF-8 JSON with a trailing newline.
    """
    return canonical_json(lock.to_json())


def read_lock(path: Path) -> Lock:
    """Read a required lock strictly.

    Args:
        path: Lock file.

    Returns:
        Typed lock.

    Raises:
        MissingLockError: If the file does not exist.
    """
    if not path.is_file():
        raise MissingLockError(f"{path.name} not found; {LOCK_HINT}")
    return loads(path.read_bytes())


def require_canonical(*, path: Path, lock: Lock) -> None:
    """Reject a lock whose bytes are not the canonical encoding.

    Args:
        path: Lock file.
        lock: Its parsed content.

    Raises:
        LockFormatError: If the bytes differ from the canonical encoding.
    """
    if path.read_bytes() != dumps(lock):
        raise LockFormatError(
            f"{path.name} is not canonical (sorted keys, 2-space indent, LF, "
            f"trailing newline); {LOCK_HINT}"
        )


def write_lock(*, path: Path, lock: Lock) -> bool:
    """Publish the canonical lock atomically when its bytes change.

    Args:
        path: Lock file.
        lock: Typed lock.

    Returns:
        Whether the file was written.
    """
    data = dumps(lock)
    if path.is_file() and path.read_bytes() == data:
        return False
    atomic_write(path=path, data=data)
    return True
