"""Registry parsing, schema validation, and baked-index rendering."""

from __future__ import annotations

import json
import re
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import yaml

from vendor_registry.vendor import Vendor

_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_VENDOR_REQUIRED_FIELDS = frozenset(
    {"id", "repo", "sha", "skillRoots", "license", "homepage"},
)
_VENDOR_OPTIONAL_FIELDS = frozenset({"displayRef"})
_VENDOR_FIELDS = _VENDOR_REQUIRED_FIELDS | _VENDOR_OPTIONAL_FIELDS


def load_registry(*, registry_path: Path) -> tuple[Vendor, ...]:
    """Load and fail-closed validate the vendor registry.

    Args:
        registry_path: Path to the ``vendors.yaml`` registry.

    Returns:
        Validated vendor records in source order.

    Raises:
        TypeError: If registry data has an invalid type.
        ValueError: If the registry violates its schema.
    """
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"vendors"}:
        msg = "vendors.yaml must contain exactly one 'vendors' mapping key"
        raise ValueError(msg)
    raw_vendors = data["vendors"]
    if not isinstance(raw_vendors, list) or not raw_vendors:
        msg = "vendors.yaml 'vendors' must be a non-empty list"
        raise ValueError(msg)

    vendors = tuple(
        _parse_vendor(raw_vendor=raw_vendor, position=position)
        for position, raw_vendor in enumerate(raw_vendors, start=1)
    )
    ids = [vendor.id for vendor in vendors]
    if len(ids) != len(set(ids)):
        msg = "vendors.yaml vendor ids must be unique"
        raise ValueError(msg)
    return vendors


def _parse_vendor(*, raw_vendor: object, position: int) -> Vendor:
    """Validate and convert one raw vendor mapping.

    Args:
        raw_vendor: YAML value for one vendor.
        position: One-based vendor position for error messages.

    Returns:
        Validated vendor record.

    Raises:
        TypeError: If the vendor is not a mapping.
        ValueError: If a required field is invalid.
    """
    if not isinstance(raw_vendor, dict):
        msg = f"Vendor {position} must be a mapping"
        raise TypeError(msg)
    raw_keys = set(raw_vendor)
    missing = _VENDOR_REQUIRED_FIELDS - raw_keys
    unknown = raw_keys - _VENDOR_FIELDS
    if missing or unknown:
        msg = (
            f"Vendor {position} must contain required fields "
            f"{', '.join(sorted(_VENDOR_REQUIRED_FIELDS))}"
            f" and may include optional: {', '.join(sorted(_VENDOR_OPTIONAL_FIELDS))}"
        )
        raise ValueError(msg)
    if "displayRef" in raw_vendor:
        display_ref = _required_string(
            value=raw_vendor["displayRef"],
            field="displayRef",
            position=position,
        )
        if _SHA_PATTERN.fullmatch(display_ref.strip().lower()) is not None:
            # Reject bare SHAs in the consumer-facing pin field.
            msg = f"Vendor {position} displayRef must not be a commit SHA"
            raise ValueError(msg)

    vendor_id = _required_string(
        value=raw_vendor["id"],
        field="id",
        position=position,
    )
    if _ID_PATTERN.fullmatch(vendor_id) is None:
        msg = f"Vendor {position} id must be a lowercase slug"
        raise ValueError(msg)
    repo = _required_string(
        value=raw_vendor["repo"],
        field="repo",
        position=position,
    )
    if _REPO_PATTERN.fullmatch(repo) is None:
        msg = f"Vendor {position} repo must be owner/name"
        raise ValueError(msg)
    sha = _required_string(
        value=raw_vendor["sha"],
        field="sha",
        position=position,
    )
    if _SHA_PATTERN.fullmatch(sha) is None:
        msg = f"Vendor {position} sha must be a 40-character lowercase hex commit SHA"
        raise ValueError(msg)
    license_name = _required_string(
        value=raw_vendor["license"],
        field="license",
        position=position,
    )
    homepage = _required_string(
        value=raw_vendor["homepage"],
        field="homepage",
        position=position,
    )
    parsed_homepage = urlparse(homepage)
    if parsed_homepage.scheme not in {"http", "https"} or not parsed_homepage.netloc:
        msg = f"Vendor {position} homepage must be an http(s) URL"
        raise ValueError(msg)
    skill_roots = _parse_skill_roots(
        value=raw_vendor["skillRoots"],
        position=position,
    )
    return Vendor(
        id=vendor_id,
        repo=repo,
        sha=sha,
        skill_roots=skill_roots,
        license=license_name,
        homepage=homepage,
    )


def _required_string(*, value: object, field: str, position: int) -> str:
    """Return a non-empty string field or raise a schema error.

    Args:
        value: Raw YAML field value.
        field: Field name for the error message.
        position: One-based vendor position for the error message.

    Returns:
        The validated non-empty string.

    Raises:
        TypeError: If the field is not a string.
        ValueError: If the field is blank.
    """
    if not isinstance(value, str):
        msg = f"Vendor {position} {field} must be a string"
        raise TypeError(msg)
    if not value.strip():
        msg = f"Vendor {position} {field} must not be empty"
        raise ValueError(msg)
    return value


def _parse_skill_roots(*, value: object, position: int) -> tuple[str, ...]:
    """Validate the non-empty list of POSIX skill-root globs.

    Args:
        value: Raw YAML ``skillRoots`` value.
        position: One-based vendor position for error messages.

    Returns:
        Skill-root patterns as an immutable tuple.

    Raises:
        TypeError: If the roots are not a string list.
        ValueError: If a root is unsafe, blank, or duplicated.
    """
    if not isinstance(value, list) or not value:
        msg = f"Vendor {position} skillRoots must be a non-empty list"
        raise ValueError(msg)
    roots: list[str] = []
    for root in value:
        if not isinstance(root, str):
            msg = f"Vendor {position} skillRoots entries must be strings"
            raise TypeError(msg)
        if root.startswith("/"):
            msg = (
                f"Vendor {position} skillRoots entries must be relative, "
                "non-empty paths"
            )
            raise ValueError(msg)
        normalized = root.strip("/")
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts:
            msg = (
                f"Vendor {position} skillRoots entries must be relative, "
                "non-empty paths"
            )
            raise ValueError(msg)
        roots.append(normalized)
    if len(roots) != len(set(roots)):
        msg = f"Vendor {position} skillRoots entries must be unique"
        raise ValueError(msg)
    return tuple(roots)


def discover_skills(
    *,
    paths: list[str],
    skill_roots: tuple[str, ...],
) -> list[dict[str, str]]:
    """Find skill directories represented by ``SKILL.md`` blobs below roots.

    Args:
        paths: POSIX paths returned by a repository tree listing.
        skill_roots: Skill-root paths or globs from the registry.

    Returns:
        Sorted skill records containing stable ``name`` and ``path`` fields.
    """
    skills: list[dict[str, str]] = []
    for path in paths:
        pure_path = PurePosixPath(path)
        if pure_path.name != "SKILL.md":
            continue
        skill_path = pure_path.parent.as_posix()
        if _is_within_skill_roots(
            skill_path=skill_path,
            skill_roots=skill_roots,
        ):
            skills.append({"name": pure_path.parent.name, "path": skill_path})
    return sorted(skills, key=lambda skill: skill["path"])


def _is_within_skill_roots(
    *,
    skill_path: str,
    skill_roots: tuple[str, ...],
) -> bool:
    """Return whether a skill directory is descended from a root glob.

    Args:
        skill_path: POSIX path to a directory containing ``SKILL.md``.
        skill_roots: Root paths or globs configured by the vendor.

    Returns:
        Whether the skill resides below at least one configured root.
    """
    skill_parts = PurePosixPath(skill_path).parts
    return any(
        len(skill_parts) > len(root_parts)
        and all(
            fnmatchcase(skill_part, root_part)
            for skill_part, root_part in zip(
                skill_parts,
                root_parts,
                strict=False,
            )
        )
        for skill_root in skill_roots
        if (root_parts := PurePosixPath(skill_root).parts)
    )


def render_index(*, vendor: Vendor, skills: list[dict[str, str]]) -> str:
    """Render one stable baked vendor index.

    Args:
        vendor: Source registry record.
        skills: Skills discovered from the pinned repository tree.

    Returns:
        Pretty JSON text with a trailing newline.
    """
    payload = {
        "vendor": {
            "id": vendor.id,
            "repo": vendor.repo,
            "sha": vendor.sha,
            "skillRoots": list(vendor.skill_roots),
        },
        "skills": skills,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def validate_index(*, index_path: Path, vendor: Vendor) -> None:
    """Validate a baked index's metadata and skill-list invariants offline.

    Args:
        index_path: Path to the committed vendor JSON index.
        vendor: Registry record that the index must describe.

    Raises:
        ValueError: If the index is absent, malformed, stale, or inconsistent.
        TypeError: If the index skills payload is not a list.
    """
    if not index_path.is_file():
        msg = f"Missing vendor index: {index_path}"
        raise ValueError(msg)
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        msg = f"Invalid JSON in vendor index: {index_path}"
        raise ValueError(msg) from error
    if not isinstance(payload, dict) or set(payload) != {"vendor", "skills"}:
        msg = f"Vendor index {index_path} must contain exactly vendor and skills"
        raise ValueError(msg)
    expected_vendor = {
        "id": vendor.id,
        "repo": vendor.repo,
        "sha": vendor.sha,
        "skillRoots": list(vendor.skill_roots),
    }
    if payload["vendor"] != expected_vendor:
        msg = f"Vendor index metadata does not match vendors.yaml: {index_path}"
        raise ValueError(msg)
    skills = payload["skills"]
    if not isinstance(skills, list):
        msg = f"Vendor index skills must be a list: {index_path}"
        raise TypeError(msg)
    expected_skills = _validate_index_skills(skills=skills, vendor=vendor)
    if skills != expected_skills:
        msg = (
            "Vendor index skills must be sorted, unique, and root-consistent: "
            f"{index_path}"
        )
        raise ValueError(msg)


def _validate_index_skills(
    *,
    skills: list[object],
    vendor: Vendor,
) -> list[dict[str, str]]:
    """Validate baked index skill entries and return canonical ordering.

    Args:
        skills: Raw JSON ``skills`` entries.
        vendor: Vendor supplying allowed skill-root globs.

    Returns:
        Canonically sorted skill records.

    Raises:
        ValueError: If a skill entry does not meet index invariants.
        TypeError: If a skill name or path is not a string.
    """
    normalized: list[dict[str, str]] = []
    for skill in skills:
        if not isinstance(skill, dict) or set(skill) != {"name", "path"}:
            msg = "Vendor index skills must contain name/path mappings"
            raise ValueError(msg)
        name = skill["name"]
        path = skill["path"]
        if not isinstance(name, str) or not isinstance(path, str):
            msg = "Vendor index skill name and path must be strings"
            raise TypeError(msg)
        pure_path = PurePosixPath(path)
        if (
            not name
            or pure_path.name != name
            or not _is_within_skill_roots(
                skill_path=path,
                skill_roots=vendor.skill_roots,
            )
        ):
            msg = f"Vendor index skill path is outside skillRoots: {path}"
            raise ValueError(msg)
        normalized.append({"name": name, "path": path})
    if len({skill["path"] for skill in normalized}) != len(normalized):
        msg = "Vendor index skill paths must be unique"
        raise ValueError(msg)
    return sorted(normalized, key=lambda skill: skill["path"])


def render_notice(*, vendors: tuple[Vendor, ...]) -> str:
    """Render the root NOTICE file from registry metadata.

    Args:
        vendors: Validated registry records.

    Returns:
        Markdown NOTICE text with a trailing newline.
    """
    lines = [
        "# Third-Party Notices",
        "",
        (
            "This package catalogs third-party skills at the commit pins in "
            "`vendors.yaml`."
        ),
        "",
        "## Vendor repositories",
        "",
    ]
    for vendor in vendors:
        lines.extend(
            [
                f"- [{vendor.repo}]({vendor.homepage}) — `{vendor.license}`",
            ],
        )
        if vendor.id == "anthropics":
            lines.extend(
                [
                    "  - Anthropic document skills are source-available.",
                    "    The registry field is Apache-2.0 for this catalog.",
                ],
            )
        if vendor.id == "anthropics-claude-code":
            lines.extend(
                [
                    "  - Claude Code plugin skills are subject to Anthropic's",
                    "    Commercial Terms of Service.",
                ],
            )
    return "\n".join(lines) + "\n"
