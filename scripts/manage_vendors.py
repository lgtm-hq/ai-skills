#!/usr/bin/env python3
"""Add or update SHA-pinned vendors and refresh generated artifacts.

Usage:
    uv run python scripts/manage_vendors.py add \
        --id example --repo owner/repository \
        --sha 0123456789abcdef0123456789abcdef01234567 \
        --skill-roots skills --license MIT \
        --homepage https://github.com/owner/repository
    uv run python scripts/manage_vendors.py update --id example --sha <new-sha>
    uv run python scripts/manage_vendors.py refresh
    uv run python scripts/manage_vendors.py check
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

import yaml

import bake_vendor_indexes
from vendor_registry.registry import load_registry

_SYNC_SCRIPT = (
    Path(__file__).resolve().parent / "ci" / "npm" / "sync_ai_skills_package.py"
)
_FIELD_ORDER = (
    "id",
    "repo",
    "sha",
    "displayRef",
    "skillRoots",
    "license",
    "homepage",
)
_DEFAULT_DISPLAY_REF = "latest"


def _repo_root() -> Path:
    """Return the repository root (parent of ``scripts/``).

    Returns:
        Absolute path to the repository root.
    """
    return Path(__file__).resolve().parents[1]


def _load_sync_module() -> Any:
    """Load the npm package synchronization script as a module.

    Returns:
        Loaded synchronization module, typed dynamically for reconfiguration.

    Raises:
        RuntimeError: If the synchronization script cannot be imported.
    """
    specification = importlib.util.spec_from_file_location(
        "sync_ai_skills_package",
        _SYNC_SCRIPT,
    )
    if specification is None or specification.loader is None:
        msg = f"Could not load {_SYNC_SCRIPT}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _configure_sync(*, sync: Any, repo_root: Path) -> None:
    """Point the synchronization module at a specific repository root.

    Args:
        sync: Loaded synchronization module to reconfigure.
        repo_root: Repository root whose sources drive package generation.
    """
    package_root = repo_root / "npm" / "ai-skills"
    data_root = package_root / "data"
    sync.PROJECT_ROOT = repo_root
    sync.PACKAGE_ROOT = package_root
    sync.DATA_ROOT = data_root
    sync.PACKAGE_MANIFEST = package_root / "package.json"
    sync.SOURCE_DATA = {
        repo_root / "vendors.yaml": data_root / "vendors.yaml",
        repo_root / "bundles.yaml": data_root / "bundles.yaml",
        repo_root / "NOTICE.md": package_root / "NOTICE.md",
    }


def _sync_artifacts(*, repo_root: Path, check_only: bool) -> int:
    """Render or verify the ai-skills npm package data for a repository root.

    Args:
        repo_root: Repository root containing generated sources.
        check_only: When true, report drift instead of writing files.

    Returns:
        ``0`` when synchronized (or freshly written), otherwise ``1``.
    """
    sync = _load_sync_module()
    _configure_sync(sync=sync, repo_root=repo_root)
    files = sync.rendered_files(version="0.0.0-dev")
    if check_only:
        return int(sync.check_rendered(files))
    sync.write_rendered(files)
    return 0


def _needs_quote(*, value: str) -> bool:
    """Return whether a scalar value must be double-quoted in YAML.

    Args:
        value: Scalar string destined for the registry document.

    Returns:
        Whether the value would be misparsed as plain YAML.
    """
    if not value or value != value.strip():
        return True
    if value[0] in "!&*?|>%@`\"'#,[]{}:-":
        return True
    return ": " in value or " #" in value


def _scalar(*, value: str, quote: bool = False) -> str:
    """Render a scalar for the registry document, quoting when needed.

    Args:
        value: Scalar string value.
        quote: When true, always emit a double-quoted scalar.

    Returns:
        The serialized scalar text.
    """
    if quote or _needs_quote(value=value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _dump_registry(*, vendors: list[dict[str, Any]]) -> str:
    """Serialize vendor mappings to the canonical ``vendors.yaml`` layout.

    Args:
        vendors: Ordered vendor mappings with camelCase keys.

    Returns:
        Canonical registry text with a trailing newline.
    """
    lines = ["---", "vendors:"]
    for vendor in vendors:
        emitted = False
        for field in _FIELD_ORDER:
            if field not in vendor:
                continue
            prefix = "  - " if not emitted else "    "
            emitted = True
            if field == "skillRoots":
                lines.append(f"{prefix}skillRoots:")
                lines.extend(
                    f"      - {_scalar(value=str(root))}"
                    for root in vendor["skillRoots"]
                )
                continue
            lines.append(
                f"{prefix}{field}: "
                f"{_scalar(value=str(vendor[field]), quote=field == 'sha')}",
            )
    return "\n".join(lines) + "\n"


def _read_raw_registry(*, registry_path: Path) -> list[dict[str, Any]]:
    """Load the registry into mutable vendor mappings without validation.

    Args:
        registry_path: Path to the ``vendors.yaml`` registry.

    Returns:
        Vendor mappings in source order as mutable dictionaries.

    Raises:
        TypeError: If a vendor entry is not a mapping.
        ValueError: If the document lacks a ``vendors`` list.
    """
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or "vendors" not in data
        or not isinstance(data["vendors"], list)
    ):
        msg = "vendors.yaml must contain a 'vendors' list"
        raise ValueError(msg)
    vendors: list[dict[str, Any]] = []
    for raw_vendor in data["vendors"]:
        if not isinstance(raw_vendor, dict):
            msg = "Each vendor must be a mapping"
            raise TypeError(msg)
        vendors.append(dict(raw_vendor))
    return vendors


def _write_registry(
    *,
    registry_path: Path,
    vendors: list[dict[str, Any]],
) -> None:
    """Write and re-validate the registry, restoring the original on error.

    Args:
        registry_path: Path to the ``vendors.yaml`` registry.
        vendors: Vendor mappings to serialize.

    Raises:
        TypeError: If the serialized registry fails type validation.
        ValueError: If the serialized registry violates its schema.
    """
    original = (
        registry_path.read_text(encoding="utf-8") if registry_path.is_file() else None
    )
    registry_path.write_text(_dump_registry(vendors=vendors), encoding="utf-8")
    try:
        load_registry(registry_path=registry_path)
    except (TypeError, ValueError):
        if original is not None:
            registry_path.write_text(original, encoding="utf-8")
        raise


def _build_vendor_mapping(
    *,
    vendor_id: str,
    repo: str,
    sha: str,
    skill_roots: tuple[str, ...],
    license_name: str,
    homepage: str,
    display_ref: str | None,
) -> dict[str, Any]:
    """Build a camelCase vendor mapping from add-command arguments.

    Args:
        vendor_id: Unique vendor slug.
        repo: ``owner/name`` repository slug.
        sha: 40-character lowercase hex commit SHA.
        skill_roots: One or more skill-root paths or globs.
        license_name: SPDX or descriptive license label.
        homepage: Vendor homepage URL.
        display_ref: Consumer-facing pin, defaulting to ``latest``.

    Returns:
        Ordered vendor mapping ready for serialization.
    """
    return {
        "id": vendor_id,
        "repo": repo,
        "sha": sha,
        "displayRef": display_ref if display_ref is not None else _DEFAULT_DISPLAY_REF,
        "skillRoots": list(skill_roots),
        "license": license_name,
        "homepage": homepage,
    }


def _print_summary(*, action: str, vendor_id: str) -> None:
    """Print a change summary and the required manual follow-up reminders.

    Args:
        action: Human-readable verb describing the mutation.
        vendor_id: Vendor slug that was changed.
    """
    print(f"{action} vendor '{vendor_id}' in vendors.yaml.")
    print("Rebaked vendor indexes and synchronized ai-skills npm package data.")
    print()
    print("Manual follow-up still required (not automated):")
    print("  - Add or update the vendor bullet in README.md.")
    print("  - Record the change under the Unreleased section of CHANGELOG.md.")


def refresh(*, repo_root: Path) -> None:
    """Rebake every vendor index and synchronize npm package data.

    Args:
        repo_root: Repository root containing ``vendors.yaml``.
    """
    bake_vendor_indexes.bake(repo_root=repo_root)
    _sync_artifacts(repo_root=repo_root, check_only=False)


def check(*, repo_root: Path) -> int:
    """Verify baked indexes and npm package data are current and consistent.

    Args:
        repo_root: Repository root containing generated artifacts.

    Returns:
        ``0`` when nothing is stale, otherwise ``1``.
    """
    bake_status = int(bake_vendor_indexes.check(repo_root=repo_root))
    sync_status = _sync_artifacts(repo_root=repo_root, check_only=True)
    return max(bake_status, sync_status)


def add(
    *,
    repo_root: Path,
    vendor_id: str,
    repo: str,
    sha: str,
    skill_roots: tuple[str, ...],
    license_name: str,
    homepage: str,
    display_ref: str | None,
) -> None:
    """Append a new vendor to the registry, then rebake and synchronize.

    Args:
        repo_root: Repository root containing ``vendors.yaml``.
        vendor_id: Unique vendor slug.
        repo: ``owner/name`` repository slug.
        sha: 40-character lowercase hex commit SHA.
        skill_roots: One or more skill-root paths or globs.
        license_name: SPDX or descriptive license label.
        homepage: Vendor homepage URL.
        display_ref: Consumer-facing pin, defaulting to ``latest``.

    Raises:
        ValueError: If the vendor id already exists in the registry.
    """
    registry_path = repo_root / "vendors.yaml"
    vendors = _read_raw_registry(registry_path=registry_path)
    if any(vendor.get("id") == vendor_id for vendor in vendors):
        msg = f"Vendor id already exists: {vendor_id}"
        raise ValueError(msg)
    vendors.append(
        _build_vendor_mapping(
            vendor_id=vendor_id,
            repo=repo,
            sha=sha,
            skill_roots=skill_roots,
            license_name=license_name,
            homepage=homepage,
            display_ref=display_ref,
        ),
    )
    _write_registry(registry_path=registry_path, vendors=vendors)
    refresh(repo_root=repo_root)
    _print_summary(action="Added", vendor_id=vendor_id)


def update(
    *,
    repo_root: Path,
    vendor_id: str,
    repo: str | None,
    sha: str | None,
    skill_roots: tuple[str, ...] | None,
    license_name: str | None,
    homepage: str | None,
    display_ref: str | None,
) -> None:
    """Patch provided fields on an existing vendor, then rebake and synchronize.

    Args:
        repo_root: Repository root containing ``vendors.yaml``.
        vendor_id: Slug of the vendor to update.
        repo: New ``owner/name`` slug, or ``None`` to keep the current value.
        sha: New commit SHA, or ``None`` to keep the current value.
        skill_roots: New skill-root list, or ``None`` to keep the current value.
        license_name: New license label, or ``None`` to keep the current value.
        homepage: New homepage URL, or ``None`` to keep the current value.
        display_ref: New display ref, or ``None`` to keep the current value.

    Raises:
        ValueError: If the vendor id is not present in the registry.
    """
    registry_path = repo_root / "vendors.yaml"
    vendors = _read_raw_registry(registry_path=registry_path)
    target = next(
        (vendor for vendor in vendors if vendor.get("id") == vendor_id),
        None,
    )
    if target is None:
        msg = f"Unknown vendor id: {vendor_id}"
        raise ValueError(msg)
    patch: dict[str, Any] = {
        "repo": repo,
        "sha": sha,
        "skillRoots": list(skill_roots) if skill_roots is not None else None,
        "license": license_name,
        "homepage": homepage,
        "displayRef": display_ref,
    }
    target.update(
        {field: value for field, value in patch.items() if value is not None},
    )
    _write_registry(registry_path=registry_path, vendors=vendors)
    refresh(repo_root=repo_root)
    _print_summary(action="Updated", vendor_id=vendor_id)


def _add_vendor_arguments(
    *,
    parser: argparse.ArgumentParser,
    require_fields: bool,
) -> None:
    """Register shared vendor field flags on an ``add``/``update`` subparser.

    Args:
        parser: Subparser to receive the vendor field flags.
        require_fields: Whether the mutable fields are required (``add``).
    """
    parser.add_argument("--id", dest="vendor_id", required=True, help="Vendor slug")
    parser.add_argument(
        "--repo",
        required=require_fields,
        help="Vendor repository as owner/name",
    )
    parser.add_argument(
        "--sha",
        required=require_fields,
        help="40-character lowercase hex commit SHA",
    )
    parser.add_argument(
        "--skill-roots",
        dest="skill_roots",
        action="append",
        required=require_fields,
        metavar="PATH",
        help="Skill-root path or glob (repeatable)",
    )
    parser.add_argument(
        "--license",
        dest="license_name",
        required=require_fields,
        help="License label",
    )
    parser.add_argument(
        "--homepage",
        required=require_fields,
        help="Vendor homepage URL",
    )
    parser.add_argument(
        "--display-ref",
        dest="display_ref",
        default=None,
        help="Consumer-facing pin (default: latest on add)",
    )


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with add/update/refresh/check commands.

    Returns:
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root override (default: parent of scripts/)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_parser = subparsers.add_parser(
        "add",
        parents=[common],
        help="Append a vendor, then rebake and synchronize",
    )
    _add_vendor_arguments(parser=add_parser, require_fields=True)
    update_parser = subparsers.add_parser(
        "update",
        parents=[common],
        help="Patch an existing vendor, then rebake and synchronize",
    )
    _add_vendor_arguments(parser=update_parser, require_fields=False)
    subparsers.add_parser(
        "refresh",
        parents=[common],
        help="Rebake indexes and synchronize npm data (no YAML changes)",
    )
    subparsers.add_parser(
        "check",
        parents=[common],
        help="Verify baked indexes and npm data are current",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch a vendor management command.

    Args:
        argv: CLI arguments, defaulting to process arguments.

    Returns:
        Process exit code.
    """
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root if args.repo_root is not None else _repo_root()
    try:
        if args.command == "add":
            add(
                repo_root=repo_root,
                vendor_id=args.vendor_id,
                repo=args.repo,
                sha=args.sha,
                skill_roots=tuple(args.skill_roots),
                license_name=args.license_name,
                homepage=args.homepage,
                display_ref=args.display_ref,
            )
            return 0
        if args.command == "update":
            update(
                repo_root=repo_root,
                vendor_id=args.vendor_id,
                repo=args.repo,
                sha=args.sha,
                skill_roots=(
                    tuple(args.skill_roots) if args.skill_roots is not None else None
                ),
                license_name=args.license_name,
                homepage=args.homepage,
                display_ref=args.display_ref,
            )
            return 0
        if args.command == "refresh":
            refresh(repo_root=repo_root)
            return 0
        return check(repo_root=repo_root)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
