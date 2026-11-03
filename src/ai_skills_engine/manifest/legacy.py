"""Deterministic derived legacy registries with a byte-preserving drift gate."""

import difflib
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ai_skills_engine.generate.marketplace import _load_bundles, _validate_bundles
from ai_skills_engine.manifest.edit import dump_document, patch_document
from ai_skills_engine.manifest.layout import decode_template
from ai_skills_engine.manifest.load import load_manifest, read_document
from ai_skills_engine.manifest.transaction import restore_files, snapshot_files
from ai_skills_engine.registry.registry import load_registry

GENERATED_HEADER = "# generated from ai-skills.yaml; do not edit.\n"
LEGACY_PACKAGE_FIELDS = frozenset(
    {
        "id",
        "description",
        "skillsRoot",
        "skills",
        "extraSkills",
        "extraFiles",
        "renameSkills",
        "agents",
    }
)


def _check_dependencies(*, declaration: dict[str, Any], location: str) -> None:
    """Reject payload requirements that legacy publication cannot honor.

    Args:
        declaration: Validated package or capability declaration.
        location: Qualified identity for an actionable diagnostic.

    Raises:
        ValueError: If dependencies or resources would be silently discarded.
    """
    for field in ("requires", "resources"):
        if declaration.get(field):
            raise ValueError(
                f"Legacy publication cannot represent {field} in {location}; "
                "use manifest-aware publication for dependencies and resources"
            )


def _check_publication(data: dict[str, Any]) -> None:
    """Reject publication narrowing that legacy readers cannot enforce.

    Args:
        data: Validated manifest declarations.

    Raises:
        ValueError: If compatibility output would silently publish extra content.
    """
    publisher = data["publisher"]["id"]
    exports = {
        value if "/" in value else f"{publisher}/{value}"
        for value in data.get("exports", [])
    }
    required = set()
    for package in data.get("packages", []):
        qualified = f"{publisher}/{package['id']}"
        if package.get("x-legacy-ungrouped"):
            if qualified in exports:
                raise ValueError(
                    f"Legacy publication cannot represent export {qualified}: "
                    "ungrouped content is reserved for non-marketplace selection"
                )
        else:
            required.add(qualified)
    for vendor in data.get("vendors", []):
        packages = {
            f"{vendor['id']}/{package['id']}"
            for package in vendor.get("mapping", {}).get("packages", [])
        }
        required.update(packages)
        if (
            "include" in vendor and not packages.issubset(set(vendor["include"]))
        ) or vendor.get("exclude"):
            raise ValueError(
                f"Legacy publication cannot represent include/exclude for vendor "
                f"{vendor['id']}: compatibility output requires every mapped package "
                "included and no exclusions; use manifest-aware publication "
                "for narrowing"
            )
    if missing := required - exports:
        raise ValueError(
            "Legacy publication cannot represent unexported packages: "
            + ", ".join(sorted(missing))
            + ". Explicitly export these packages or use manifest-aware publication; "
            "imports never imply re-export."
        )


def legacy_documents(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Project manifest declarations to the old consumer-facing shape.

    Args:
        data: Validated manifest with optional formatting extensions.

    Returns:
        Authoritative legacy values by filename.

    Raises:
        ValueError: If a new declaration cannot be represented by legacy readers.
    """
    _check_publication(data)
    bundles: dict[str, Any] = {**data.get("x-legacy-fields", {}), "groups": {}}
    destinations: dict[tuple[str, Any], str] = {}
    for package in data.get("packages", []):
        destination = (
            ("ungrouped", None)
            if package.get("x-legacy-ungrouped")
            else ("groups", package.get("x-legacy-group", package["id"]))
        )
        if destination in destinations:
            raise ValueError(
                f"Legacy registry has duplicate destination {destination!r} for "
                f"packages {destinations[destination]} and {package['id']}"
            )
        destinations[destination] = package["id"]
        qualified = f"{data['publisher']['id']}/{package['id']}"
        _check_dependencies(declaration=package, location=qualified)
        skills = []
        for capability in package.get("capabilities", []):
            _check_dependencies(
                declaration=capability,
                location=(
                    f"{qualified}:{capability.get('role', 'skill')}/{capability['id']}"
                ),
            )
            path = capability["path"]
            if (
                capability.get("role", "skill") != "skill"
                or not path.startswith("skills/")
                or path.count("/") != 1
            ):
                raise ValueError(f"Legacy registry cannot represent capability: {path}")
            skills.append(path.removeprefix("skills/"))
        if package.get("x-legacy-ungrouped"):
            bundles["ungrouped"] = skills
        else:
            bundles["groups"][package.get("x-legacy-group", package["id"])] = {
                **package.get("x-legacy-fields", {}),
                **{
                    field: package[field]
                    for field in ("id", "name", "description")
                    if field in package
                },
                "skills": skills,
            }
    vendors = []
    for vendor in data.get("vendors", []):
        mapping = vendor.get("mapping")
        if mapping is None:
            raise ValueError(
                f"Legacy registry cannot represent manifest vendor: {vendor['id']}"
            )
        for package in mapping.get("packages", []):
            for name, capability in package.get("capabilities", {}).items():
                _check_dependencies(
                    declaration=capability,
                    location=f"{vendor['id']}/{package['id']}:skill/{name}",
                )
        raw = {
            key: value
            for key, value in vendor.items()
            if key
            in {"id", "repo", "sha", "branch", "displayRef", "license", "homepage"}
        }
        raw["skillRoots"] = mapping["skillRoots"]
        if "packages" in mapping:
            raw["plugins"] = [
                {
                    key: value
                    for key, value in package.items()
                    if key in LEGACY_PACKAGE_FIELDS
                }
                for package in mapping["packages"]
            ]
        vendors.append(raw)
    return {"bundles.yaml": bundles, "vendors.yaml": {"vendors": vendors}}


def render_legacy(repo_root: Path) -> dict[Path, bytes]:
    """Render both registries from validated declarations and layout templates.

    Args:
        repo_root: Author repository with an authoritative manifest.

    Returns:
        Destination paths and exact generated UTF-8 bytes.

    Raises:
        ValueError: If either rendered document fails its compatibility consumer.
    """
    path = repo_root / "ai-skills.yaml"
    load_manifest(path)
    data = read_document(path)
    templates = data.get("x-legacy-format", {})
    files = {
        repo_root
        / name: (
            GENERATED_HEADER
            + (
                patch_document(
                    text=decode_template(templates[name]).removeprefix(
                        GENERATED_HEADER
                    ),
                    data=document,
                )
                if name in templates
                else dump_document(document)
            )
        ).encode("utf-8")
        for name, document in legacy_documents(data).items()
    }
    # Both real readers must see the rendered pair, including their cross-file
    # collision checks. Never validate against stale destination files or write
    # one registry before discovering that the other is incompatible.
    # Parse scratch bytes, but discover skills from the author's actual tree;
    # do not synthesize payloads or copy/execute any vendor content.
    with TemporaryDirectory(prefix="ai-skills-legacy-") as directory:
        scratch = Path(directory)
        for destination, content in files.items():
            (scratch / destination.name).write_bytes(content)
        for name, reader in (
            (
                "bundles.yaml",
                lambda: _validate_bundles(
                    repo_root=repo_root,
                    bundles=_load_bundles(repo_root=scratch),
                ),
            ),
            (
                "vendors.yaml",
                lambda: load_registry(registry_path=scratch / "vendors.yaml"),
            ),
        ):
            try:
                reader()
            except (OSError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Legacy publication cannot satisfy {name} reader: {exc}"
                ) from exc
    return files


def write_legacy(repo_root: Path, *, check: bool = False) -> int:
    """Write derived registries, or report byte drift without writing anything.

    Args:
        repo_root: Author repository root.
        check: Compare only, returning nonzero for any drift.

    Returns:
        Zero when written/current, one when check finds drift.
    """
    files = render_legacy(repo_root)
    originals = snapshot_files(files)
    drift = False
    try:
        for path, expected in files.items():
            previous = originals[path]
            actual = previous[0] if previous is not None else b""
            if actual == expected:
                continue
            if check:
                drift = True
                sys.stderr.writelines(
                    difflib.unified_diff(
                        actual.decode().splitlines(keepends=True),
                        expected.decode().splitlines(keepends=True),
                        fromfile=path.name,
                        tofile="generated from ai-skills.yaml",
                    )
                )
            else:
                path.write_bytes(expected)
    except OSError as error:
        if not check:
            restore_files(originals=originals, error=error)
        raise
    return int(drift)
