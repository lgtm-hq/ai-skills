"""Digest pins and SHA-256 verification of uncompressed package tars.

A package's pin comes from the first available source: the consumer profile,
the repository ``ai-skills.lock``, ``--digest``, then the ``.sha256`` sidecar
published beside the tar (first install only). ``--frozen`` accepts only a
recorded pin (profile or lock). Every tar is hashed and compared before any
index inside it is read, and before anything is written.
"""

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path
from typing import Any

from ai_skills_engine.install.artifact_index import artifact_name, embedded_index
from ai_skills_engine.install.errors import InstallError
from ai_skills_engine.install.profile import DIGEST
from ai_skills_engine.install.strict_json import load_object
from ai_skills_engine.lockmodel.lock import LOCK_VERSION

LOCK_FILENAME = "ai-skills.lock"
_SIDECAR = re.compile(r"([0-9a-f]{64})  (\S+)\n?")


class PinSource(StrEnum):
    """Where a package's expected digest came from, highest priority first."""

    PROFILE = auto()
    LOCK = auto()
    DIGEST = auto()
    SIDECAR = auto()


@dataclass(frozen=True)
class Pins:
    """Candidate pins by package, one mapping per source.

    Attributes:
        profile: Consumer profile pins; empty for ``update`` (which moves them).
        lock: Repository lock ``artifactDigest`` values.
        flags: ``--digest`` values.
        frozen: Accept only profile or lock pins.
    """

    profile: Mapping[str, str]
    lock: Mapping[str, str]
    flags: Mapping[str, str]
    frozen: bool = False


@dataclass(frozen=True)
class VerifiedPackage:
    """A package tar whose bytes match its pin.

    Attributes:
        id: Qualified package ID.
        digest: Verified ``sha256:`` digest of the uncompressed tar.
        source: Where the pin came from.
        index: Schema-valid index embedded in the verified tar.
    """

    id: str
    digest: str
    source: PinSource
    index: Mapping[str, Any]


def read_lock_pins(path: Path) -> dict[str, str]:
    """Read package ``artifactDigest`` pins from a repository lock, if present.

    Only the lock version and pins are interpreted; the build plane owns the
    rest of the lock contract.

    Args:
        path: Candidate ``ai-skills.lock``.

    Returns:
        Digest by package ID; empty if the file does not exist.

    Raises:
        InstallError: For an unknown lock version or malformed pin entries.
    """
    if not path.is_file():
        return {}
    lock = load_object(path.read_bytes(), source=str(path))
    if lock.get("lockVersion") != LOCK_VERSION:
        raise InstallError(
            f"{path}: unsupported lockVersion {lock.get('lockVersion')!r}"
        )
    packages = lock.get("packages")
    if not isinstance(packages, list):
        raise InstallError(f"{path}: packages must be a list")
    pins = {}
    for item in packages:
        package = item.get("id") if isinstance(item, dict) else None
        pin = item.get("artifactDigest") if isinstance(item, dict) else None
        if not isinstance(package, str) or not isinstance(pin, str):
            raise InstallError(f"{path}: package entries need id and artifactDigest")
        if not DIGEST.fullmatch(pin):
            raise InstallError(f"{path}: {package} artifactDigest is malformed")
        pins[package] = pin
    return pins


def parse_digest_flags(
    values: Sequence[str], packages: Sequence[str]
) -> dict[str, str]:
    """Parse ``--digest PACKAGE=sha256:HEX`` (or a bare digest for one package).

    Args:
        values: Raw flag values.
        packages: Selected package IDs.

    Returns:
        Digest by package ID.

    Raises:
        InstallError: For malformed values or packages outside the selection.
    """
    pins = {}
    for value in values:
        package, separator, pin = value.rpartition("=")
        if not separator:
            if len(packages) != 1:
                raise InstallError("a bare --digest needs exactly one selected package")
            package = packages[0]
        if package not in packages:
            raise InstallError(f"--digest names unselected package {package!r}")
        if not DIGEST.fullmatch(pin):
            raise InstallError(f"--digest {value!r}: expected sha256:<64 hex>")
        pins[package] = pin
    return pins


def _sidecar(directory: Path, package: str) -> str | None:
    """Read the published ``.sha256`` sidecar for a package tar.

    Args:
        directory: Artifact directory.
        package: Package ID.

    Returns:
        Qualified digest, or None if no sidecar exists.

    Raises:
        InstallError: If the sidecar is unreadable, malformed or names another
            file.
    """
    name = artifact_name(package)
    path = directory / (name + ".sha256")
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise InstallError(f"{path}: unreadable digest sidecar ({error})") from error
    match = _SIDECAR.fullmatch(text)
    if match is None or match.group(2) != name:
        raise InstallError(f"{path}: malformed digest sidecar")
    return "sha256:" + match.group(1)


def choose_pin(*, directory: Path, package: str, pins: Pins) -> tuple[str, PinSource]:
    """Pick the highest-priority pin for one package.

    Args:
        directory: Artifact directory (for the sidecar).
        package: Package ID.
        pins: Candidate pins.

    Returns:
        Digest and its source.

    Raises:
        InstallError: If no allowed pin exists or ``--digest`` contradicts it.
    """
    flag = pins.flags.get(package)
    ranked = [
        (pins.profile.get(package), PinSource.PROFILE),
        (pins.lock.get(package), PinSource.LOCK),
    ]
    for pin, source in ranked:
        if pin is not None:
            if flag is not None and flag != pin:
                raise InstallError(
                    f"{package}: --digest {flag} contradicts the {source} pin {pin}"
                )
            return pin, source
    if pins.frozen:
        raise InstallError(f"{package}: --frozen needs a pin in the profile or lock")
    if flag is not None:
        return flag, PinSource.DIGEST
    # Read the sidecar only when no higher-priority pin exists.
    sidecar = _sidecar(directory, package)
    if sidecar is not None:
        return sidecar, PinSource.SIDECAR
    raise InstallError(
        f"{package}: no pinned digest (profile, lock, --digest, sidecar)"
    )


def verify_packages(
    *, directory: Path, packages: Sequence[str], pins: Pins
) -> tuple[VerifiedPackage, ...]:
    """Hash every selected tar, compare it with its pin, then read its index.

    Args:
        directory: Artifact directory.
        packages: Selected package IDs.
        pins: Candidate pins.

    Returns:
        Verified packages in input order.

    Raises:
        InstallError: On any missing tar or digest mismatch.
    """
    verified = []
    for package in packages:
        expected, source = choose_pin(directory=directory, package=package, pins=pins)
        path = directory / artifact_name(package)
        if not path.is_file():
            raise InstallError(f"{package}: artifact {path.name} not found")
        data = path.read_bytes()
        actual = "sha256:" + hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise InstallError(
                f"{package}: digest mismatch: {source} pin {expected}, "
                f"artifact {actual}"
            )
        verified.append(
            VerifiedPackage(
                id=package,
                digest=actual,
                source=source,
                index=embedded_index(data, package=package),
            )
        )
    return tuple(verified)
