"""Machine-local consumer profile: pins, excludes and origin denies.

``~/.config/ai-skills/selection.yaml`` (or ``$XDG_CONFIG_HOME/ai-skills/``
when that is absolute) records one digest pin per installed package artifact
plus the consumer's excludes and denies, so ``update`` replays them. ``modes``
is reserved for delivery modes (#581) and must stay empty here. Reading is
strict; writes are atomic (temporary file, fsync, rename).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ai_skills_engine.atomic_write import atomic_write
from ai_skills_engine.install.errors import InstallError
from ai_skills_engine.install.selectors import (
    PACKAGE_ID,
    Selector,
    SelectorKind,
    make_selector,
    parse_origin,
)
from ai_skills_engine.registry.registry import load_unique_yaml_text

PROFILE_API_VERSION = "ai-skills.dev/selection/v1"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_KEYS = frozenset({"apiVersion", "artifacts", "exclude", "deny", "modes"})


@dataclass(frozen=True)
class Profile:
    """Typed consumer profile.

    Attributes:
        artifacts: Pinned digest per qualified package ID.
        exclude: Persisted capability and package excludes.
        deny: Persisted origin denies.
    """

    artifacts: Mapping[str, str] = field(default_factory=dict)
    exclude: tuple[Selector, ...] = ()
    deny: tuple[str, ...] = ()


def default_path(*, env: Mapping[str, str], home: Path) -> Path:
    """Locate the profile without touching the filesystem.

    Args:
        env: Process environment.
        home: User home directory.

    Returns:
        Profile path.
    """
    config = env.get("XDG_CONFIG_HOME", "")
    base = Path(config) if config and Path(config).is_absolute() else home / ".config"
    return base / "ai-skills" / "selection.yaml"


def _excludes(value: object) -> tuple[Selector, ...]:
    """Parse ``exclude`` entries of the form ``{capability: id}``/``{package: id}``.

    Args:
        value: Raw YAML value.

    Returns:
        Validated selectors.

    Raises:
        InstallError: For any other shape.
    """
    if not isinstance(value, list):
        raise InstallError("profile exclude must be a list")
    result = []
    for item in value:
        if not isinstance(item, dict) or len(item) != 1:
            raise InstallError("profile exclude entries need exactly one key")
        ((kind, ident),) = item.items()
        if kind not in {member.value for member in SelectorKind}:
            raise InstallError(f"unknown profile exclude kind {kind!r}")
        if not isinstance(ident, str):
            raise InstallError(f"profile exclude {kind} must be a string")
        result.append(make_selector(SelectorKind(kind), ident))
    return tuple(result)


def _denies(value: object) -> tuple[str, ...]:
    """Parse ``deny`` entries of the form ``{origin: locator}``.

    Args:
        value: Raw YAML value.

    Returns:
        Validated origins.

    Raises:
        InstallError: For any other shape.
    """
    if not isinstance(value, list):
        raise InstallError("profile deny must be a list")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"origin"}:
            raise InstallError("profile deny entries must be {origin: <locator>}")
        if not isinstance(item["origin"], str):
            raise InstallError("profile deny origin must be a string")
        result.append(parse_origin(item["origin"]))
    return tuple(result)


def _artifacts(value: object) -> dict[str, str]:
    """Parse ``artifacts`` pins.

    Args:
        value: Raw YAML value.

    Returns:
        Digest by package ID.

    Raises:
        InstallError: For a malformed package ID or digest.
    """
    if not isinstance(value, dict):
        raise InstallError("profile artifacts must be a mapping")
    for key, pin in value.items():
        if not isinstance(key, str) or not PACKAGE_ID.fullmatch(key):
            raise InstallError(f"profile artifacts: invalid package ID {key!r}")
        if not isinstance(pin, str) or not DIGEST.fullmatch(pin):
            raise InstallError(f"profile artifacts.{key}: expected sha256:<64 hex>")
    return dict(value)


def parse_profile(text: str, *, source: str) -> Profile:
    """Parse profile text strictly.

    Args:
        text: YAML document.
        source: Label used in diagnostics.

    Returns:
        Typed profile.

    Raises:
        InstallError: For unknown keys, versions, reserved data or bad values.
    """
    try:
        document = load_unique_yaml_text(text=text, source=source)
    except ValueError as error:
        raise InstallError(str(error)) from error
    if not isinstance(document, dict):
        raise InstallError(f"{source}: expected a mapping")
    unknown = sorted(set(document) - _KEYS, key=str)
    if unknown:
        raise InstallError(f"{source}: unknown key(s) {', '.join(map(str, unknown))}")
    if document.get("apiVersion") != PROFILE_API_VERSION:
        raise InstallError(f"{source}: apiVersion must be {PROFILE_API_VERSION}")
    if document.get("modes") not in (None, {}):
        raise InstallError(f"{source}: modes is reserved for delivery modes (#581)")
    try:
        return Profile(
            artifacts=_artifacts(document.get("artifacts") or {}),
            exclude=_excludes(document.get("exclude") or []),
            deny=_denies(document.get("deny") or []),
        )
    except InstallError as error:
        raise InstallError(f"{source}: {error}") from error


def load_profile(path: Path) -> Profile:
    """Read the profile, treating an absent file as empty.

    Args:
        path: Profile path.

    Returns:
        Typed profile.
    """
    if not path.exists():
        return Profile()
    return parse_profile(path.read_text(encoding="utf-8"), source=str(path))


def dump_profile(profile: Profile) -> bytes:
    """Serialize a profile deterministically.

    Args:
        profile: Typed profile.

    Returns:
        UTF-8 YAML with sorted pins, excludes and denies.
    """
    document = {
        "apiVersion": PROFILE_API_VERSION,
        "artifacts": dict(sorted(profile.artifacts.items())),
        "exclude": [{str(item.kind): item.id} for item in sorted(set(profile.exclude))],
        "deny": [{"origin": origin} for origin in sorted(set(profile.deny))],
        "modes": {},
    }
    return yaml.safe_dump(document, sort_keys=False).encode("utf-8")


def write_profile(path: Path, profile: Profile) -> None:
    """Publish the profile atomically.

    Args:
        path: Profile path.
        profile: Profile to persist.
    """
    atomic_write(path=path, data=dump_profile(profile))
