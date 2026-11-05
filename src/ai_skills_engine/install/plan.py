"""Plan an install or update from an artifact directory and the profile.

Order matters: everything that can fail (index format and schema, stale
profile entries, pins, digests, embedded metadata, closure and denies) is
checked here, before the caller writes anything.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path
from typing import Any

from ai_skills_engine.install.artifact_index import load_catalog
from ai_skills_engine.install.errors import InstallError
from ai_skills_engine.install.filter import FilterResult, filter_inventory
from ai_skills_engine.install.inventory import merge_indexes
from ai_skills_engine.install.legacy import select_packages
from ai_skills_engine.install.profile import Profile, load_profile
from ai_skills_engine.install.selectors import DenyRule, Selector, SelectorKind
from ai_skills_engine.install.verify import (
    LOCK_FILENAME,
    Pins,
    VerifiedPackage,
    parse_digest_flags,
    read_lock_pins,
    verify_packages,
)


class Command(StrEnum):
    """Install-plane command."""

    INSTALL = auto()
    UPDATE = auto()


@dataclass(frozen=True)
class Request:
    """Everything a plan may read.

    Attributes:
        command: ``install`` or ``update``.
        artifacts: Artifact directory.
        profile_path: Consumer profile path.
        repo_root: Directory whose ``ai-skills.lock`` supplies repository pins.
        excludes: New ``--exclude`` selectors.
        denies: New ``--deny-origin`` values.
        digests: ``--digest`` values.
        frozen: Accept only recorded pins and never change the profile.
        skills: Legacy ``--skill`` plugin IDs.
        bundle: Legacy ``--bundle`` plugin ID.
        vendor: Legacy ``--vendor`` publisher ID.
    """

    command: Command
    artifacts: Path
    profile_path: Path
    repo_root: Path
    excludes: tuple[Selector, ...] = ()
    denies: tuple[str, ...] = ()
    digests: tuple[str, ...] = ()
    frozen: bool = False
    skills: tuple[str, ...] = ()
    bundle: str | None = None
    vendor: str | None = None


@dataclass(frozen=True)
class Plan:
    """Verified packages, the filter result and the profile to persist.

    Attributes:
        packages: Verified package artifacts.
        result: Kept and removed sets.
        profile: Profile after this command.
        changed: Whether ``profile`` differs from the loaded profile.
    """

    packages: tuple[VerifiedPackage, ...]
    result: FilterResult
    profile: Profile
    changed: bool


def _packages(request: Request, profile: Profile, catalog: Sequence[str]) -> list[str]:
    """Choose package artifacts for the command.

    Args:
        request: Command request.
        profile: Loaded profile.
        catalog: Package IDs in the catalog index.

    Returns:
        Selected package IDs.

    Raises:
        InstallError: For ``update`` without recorded packages or stale pins.
    """
    if request.command is Command.INSTALL:
        return list(
            select_packages(
                packages=catalog,
                skills=request.skills,
                bundle=request.bundle,
                vendor=request.vendor,
            )
        )
    if not profile.artifacts:
        raise InstallError("update: the profile records no artifacts; run install")
    stale = sorted(set(profile.artifacts) - set(catalog))
    if stale:
        raise InstallError(
            "stale profile entry: "
            + ", ".join(f"artifacts.{item}" for item in stale)
            + " is not in the artifact"
        )
    return list(
        select_packages(
            packages=sorted(profile.artifacts),
            skills=request.skills,
            bundle=request.bundle,
            vendor=request.vendor,
        )
    )


def _check_selectors(
    *, profile: Profile, request: Request, catalog: Mapping[str, Any]
) -> None:
    """Fail when a persisted or new exclude no longer matches anything.

    Args:
        profile: Loaded profile.
        request: Command request.
        catalog: Catalog index.

    Raises:
        InstallError: Naming every stale selector.
    """
    known = {
        SelectorKind.PACKAGE: {item["id"] for item in catalog["packages"]},
        SelectorKind.CAPABILITY: {
            record["id"]
            for package in catalog["packages"]
            for record in package["capabilities"]
        },
    }
    stale = [
        f"{'profile' if item in profile.exclude else '--exclude'} {item}"
        for item in sorted(set(profile.exclude) | set(request.excludes))
        if item.id not in known[item.kind]
    ]
    if stale:
        raise InstallError("stale selector matches nothing: " + "; ".join(stale))


def _check_roots(
    verified: Iterable[VerifiedPackage], catalog: Mapping[str, Any]
) -> None:
    """Require the catalog index to agree with each verified tar's own index.

    Args:
        verified: Verified packages.
        catalog: Catalog index.

    Raises:
        InstallError: If a package tree digest differs.
    """
    trees = {item["id"]: item["treeDigest"] for item in catalog["packages"]}
    for package in verified:
        embedded = {item["id"]: item for item in package.index["packages"]}
        root = embedded.get(package.id)
        if root is None or root["treeDigest"] != trees.get(package.id):
            raise InstallError(f"{package.id}: catalog index disagrees with artifact")


def plan(request: Request) -> Plan:
    """Verify, filter and compute the next profile without writing.

    Args:
        request: Command request.

    Returns:
        Complete plan.

    Raises:
        InstallError: For any refused input.
    """
    profile = load_profile(request.profile_path)
    catalog = load_catalog(request.artifacts)
    if request.frozen and (request.excludes or request.denies or request.digests):
        raise InstallError(
            "--frozen restores recorded pins and selection; omit --exclude, "
            "--deny-origin and --digest"
        )
    packages = _packages(request, profile, [item["id"] for item in catalog["packages"]])
    _check_selectors(profile=profile, request=request, catalog=catalog)
    use_profile = request.command is Command.INSTALL or request.frozen
    pins = Pins(
        profile=profile.artifacts if use_profile else {},
        lock=read_lock_pins(request.repo_root / LOCK_FILENAME),
        flags=parse_digest_flags(request.digests, packages),
        frozen=request.frozen,
    )
    verified = verify_packages(
        directory=request.artifacts, packages=packages, pins=pins
    )
    _check_roots(verified, catalog)
    rules = [DenyRule(origin=item, source="profile") for item in profile.deny]
    rules += [DenyRule(origin=item, source="--deny-origin") for item in request.denies]
    result = filter_inventory(
        merge_indexes(item.index for item in verified),
        excludes=(*profile.exclude, *request.excludes),
        denies=rules,
    )
    following = Profile(
        artifacts={**profile.artifacts, **{item.id: item.digest for item in verified}},
        exclude=tuple(sorted(set(profile.exclude) | set(request.excludes))),
        deny=tuple(sorted(set(profile.deny) | set(request.denies))),
    )
    current = Profile(
        artifacts=dict(profile.artifacts),
        exclude=tuple(sorted(set(profile.exclude))),
        deny=tuple(sorted(set(profile.deny))),
    )
    return Plan(
        packages=verified,
        result=result,
        profile=following,
        changed=following != current or not request.profile_path.exists(),
    )
