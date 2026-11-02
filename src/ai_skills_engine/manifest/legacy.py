"""Deterministic derived legacy registries with a byte-preserving drift gate."""

import difflib
import sys
from pathlib import Path
from typing import Any

from ai_skills_engine.manifest.edit import dump_document, patch_document
from ai_skills_engine.manifest.layout import decode_template
from ai_skills_engine.manifest.load import load_manifest, read_document

GENERATED_HEADER = "# generated from ai-skills.yaml; do not edit.\n"


def legacy_documents(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Project manifest declarations to the old consumer-facing shape.

    Args:
        data: Validated manifest with optional formatting extensions.

    Returns:
        Authoritative legacy values by filename.

    Raises:
        ValueError: If a new declaration cannot be represented by legacy readers.
    """
    bundles: dict[str, Any] = {**data.get("x-legacy-fields", {}), "groups": {}}
    for package in data.get("packages", []):
        skills = []
        for capability in package.get("capabilities", []):
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
                    if key
                    in {
                        "id",
                        "description",
                        "skillsRoot",
                        "skills",
                        "extraSkills",
                        "extraFiles",
                        "renameSkills",
                        "agents",
                    }
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
    """
    path = repo_root / "ai-skills.yaml"
    load_manifest(path)
    data = read_document(path)
    templates = data.get("x-legacy-format", {})
    return {
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


def write_legacy(repo_root: Path, *, check: bool = False) -> int:
    """Write derived registries, or report byte drift without writing anything.

    Args:
        repo_root: Author repository root.
        check: Compare only, returning nonzero for any drift.

    Returns:
        Zero when written/current, one when check finds drift.
    """
    files = render_legacy(repo_root)
    drift = False
    for path, expected in files.items():
        actual = path.read_bytes() if path.exists() else b""
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
    return int(drift)
