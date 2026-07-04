#!/usr/bin/env python3
"""Generate ``skills-manifest.json`` mapping skill name to SKILL.md sha256.

The manifest is generated at **release time** and attached to the GitHub
Release (with build provenance attestation); it is intentionally **not
committed** to the repository, which would churn on every skill edit.
Consumers verify an installed skill by hashing their local ``SKILL.md``
(sha256 over raw file bytes) and comparing against the released manifest.

Output is deterministic: keys are sorted, JSON formatting is stable, and the
file ends with a trailing newline. The script is stdlib-only so it runs in
any minimal container without dependency installation.

Usage:
    uv run python scripts/generate_skills_manifest.py \
        --output skills-manifest.json
    uv run python scripts/generate_skills_manifest.py \
        --check skills-manifest.json
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from pathlib import Path

MANIFEST_FILENAME = "skills-manifest.json"


def _repo_root() -> Path:
    """Return the repository root (parent of ``scripts/``).

    Returns:
        Absolute path to the ai-skills repository root.
    """
    return Path(__file__).resolve().parents[1]


def _compute_manifest(*, repo_root: Path) -> dict[str, str]:
    """Map each skill name to the sha256 hex digest of its ``SKILL.md``.

    Args:
        repo_root: Repository root path.

    Returns:
        Mapping of skill directory name to sha256 hex digest, computed over
        the raw bytes of ``skills/<name>/SKILL.md``.

    Raises:
        FileNotFoundError: If ``skills/`` does not exist under ``repo_root``.
    """
    skills_root = repo_root / "skills"
    if not skills_root.is_dir():
        msg = f"No skills/ directory under {repo_root}"
        raise FileNotFoundError(msg)
    manifest: dict[str, str] = {}
    for entry in sorted(skills_root.iterdir()):
        skill_file = entry / "SKILL.md"
        if entry.is_dir() and skill_file.is_file():
            digest = hashlib.sha256(skill_file.read_bytes()).hexdigest()
            manifest[entry.name] = digest
    return manifest


def _render_manifest(*, manifest: dict[str, str]) -> str:
    """Serialize the manifest as stable JSON with a trailing newline.

    Args:
        manifest: Mapping of skill name to sha256 hex digest.

    Returns:
        Deterministic JSON text (sorted keys, two-space indent, trailing
        newline).
    """
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def _check(*, expected: str, manifest_path: Path) -> int:
    """Compare a manifest file on disk against freshly generated content.

    Args:
        expected: Freshly rendered manifest JSON text.
        manifest_path: Path of the manifest file to check.

    Returns:
        ``0`` if the file matches; ``1`` with a unified diff on stderr
        otherwise.
    """
    if not manifest_path.is_file():
        print(f"Manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    actual = manifest_path.read_text(encoding="utf-8")
    if actual == expected:
        return 0
    diff = difflib.unified_diff(
        actual.splitlines(keepends=True),
        expected.splitlines(keepends=True),
        fromfile=str(manifest_path),
        tofile="generated",
    )
    sys.stderr.writelines(diff)
    print(f"Manifest is stale: {manifest_path}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    """Generate or check the skills integrity manifest.

    Args:
        argv: CLI arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (``0`` on success, ``1`` on check failure).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(MANIFEST_FILENAME),
        help=f"Manifest path to write (default: {MANIFEST_FILENAME})",
    )
    parser.add_argument(
        "--check",
        type=Path,
        default=None,
        metavar="PATH",
        help="Compare PATH against generated content instead of writing",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root override (default: parent of scripts/)",
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root if args.repo_root is not None else _repo_root()
    manifest = _compute_manifest(repo_root=repo_root)
    rendered = _render_manifest(manifest=manifest)
    if args.check is not None:
        return _check(expected=rendered, manifest_path=args.check)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"Wrote {args.output} ({len(manifest)} skills)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
