"""Registry parsing, schema validation, and baked-index rendering."""

from __future__ import annotations

import json
import re
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import yaml

from vendor_registry.vendor import Vendor
from vendor_registry.vendor_plugin import VendorPlugin

_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
# Must match AGENT_SKILL_PATHS in npm/ai-skills/lib/lockfile.js.
_KNOWN_HOST_AGENTS = frozenset({"claude-code", "codex", "copilot", "cursor"})
_VENDOR_REQUIRED_FIELDS = frozenset(
    {"id", "repo", "sha", "skillRoots", "license", "homepage"},
)
_VENDOR_OPTIONAL_FIELDS = frozenset({"displayRef", "plugins"})
_VENDOR_FIELDS = _VENDOR_REQUIRED_FIELDS | _VENDOR_OPTIONAL_FIELDS
_PLUGIN_REQUIRED_FIELDS = frozenset(
    {"id", "description", "skillsRoot", "skills"},
)
_PLUGIN_OPTIONAL_FIELDS = frozenset({"extraSkills", "renameSkills", "agents"})
_PLUGIN_FIELDS = _PLUGIN_REQUIRED_FIELDS | _PLUGIN_OPTIONAL_FIELDS


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
    _validate_plugin_id_uniqueness(
        vendors=vendors,
        registry_path=registry_path,
    )
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
    plugins = _parse_plugins(
        value=raw_vendor.get("plugins", []),
        position=position,
    )
    return Vendor(
        id=vendor_id,
        repo=repo,
        sha=sha,
        skill_roots=skill_roots,
        license=license_name,
        homepage=homepage,
        plugins=plugins,
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
        roots.append(
            _parse_relative_posix_path(
                value=root,
                field="skillRoots",
                position=position,
            ),
        )
    if len(roots) != len(set(roots)):
        msg = f"Vendor {position} skillRoots entries must be unique"
        raise ValueError(msg)
    return tuple(roots)


def _parse_relative_posix_path(
    *,
    value: object,
    field: str,
    position: int,
    plugin_id: str | None = None,
) -> str:
    """Return a relative POSIX path or glob without ``..`` or absolute form.

    Args:
        value: Raw YAML path value.
        field: Field name for error messages.
        position: One-based vendor position for error messages.
        plugin_id: Plugin id when the field belongs to a plugin slice.

    Returns:
        Normalized relative POSIX path with trailing slashes stripped.

    Raises:
        TypeError: If the value is not a string.
        ValueError: If the path is blank, absolute, or escapes with ``..``.
    """
    where = _plugin_where(position=position, plugin_id=plugin_id)
    if not isinstance(value, str):
        msg = f"{where} {field} entries must be strings"
        raise TypeError(msg)
    if value.startswith("/"):
        msg = f"{where} {field} entries must be relative, non-empty paths"
        raise ValueError(msg)
    normalized = value.strip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        msg = f"{where} {field} entries must be relative, non-empty paths"
        raise ValueError(msg)
    return normalized


def _plugin_where(*, position: int, plugin_id: str | None) -> str:
    """Return a vendor/plugin prefix for schema error messages.

    Args:
        position: One-based vendor position.
        plugin_id: Plugin id when reporting a plugin-field error.

    Returns:
        ``Vendor N`` or ``Vendor N plugin <id>``.
    """
    if plugin_id is None:
        return f"Vendor {position}"
    return f"Vendor {position} plugin {plugin_id}"


def _parse_plugins(*, value: object, position: int) -> tuple[VendorPlugin, ...]:
    """Validate optional plugin slices on one vendor.

    Args:
        value: Raw YAML ``plugins`` value, or an empty list when omitted.
        position: One-based vendor position for error messages.

    Returns:
        Validated plugin records in source order.

    Raises:
        TypeError: If ``plugins`` is not a list of mappings.
        ValueError: If a plugin slice violates the schema.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        msg = f"Vendor {position} plugins must be a list"
        raise TypeError(msg)
    plugins = tuple(
        _parse_plugin(raw_plugin=raw_plugin, position=position, index=index)
        for index, raw_plugin in enumerate(value, start=1)
    )
    plugin_ids = [plugin.id for plugin in plugins]
    if len(plugin_ids) != len(set(plugin_ids)):
        msg = f"Vendor {position} plugin ids must be unique"
        raise ValueError(msg)
    rename_targets = [new for plugin in plugins for _, new in plugin.rename_skills]
    if len(rename_targets) != len(set(rename_targets)):
        msg = f"Vendor {position} renameSkills targets must be unique"
        raise ValueError(msg)
    return plugins


def _parse_plugin(
    *,
    raw_plugin: object,
    position: int,
    index: int,
) -> VendorPlugin:
    """Validate and convert one vendor plugin mapping.

    Args:
        raw_plugin: YAML value for one plugin slice.
        position: One-based vendor position for error messages.
        index: One-based plugin position within the vendor.

    Returns:
        Validated plugin record.

    Raises:
        TypeError: If the plugin is not a mapping.
        ValueError: If a required field is invalid.
    """
    if not isinstance(raw_plugin, dict):
        msg = f"Vendor {position} plugin {index} must be a mapping"
        raise TypeError(msg)
    preview_id = raw_plugin.get("id")
    plugin_label = (
        preview_id if isinstance(preview_id, str) and preview_id else str(index)
    )
    raw_keys = set(raw_plugin)
    missing = _PLUGIN_REQUIRED_FIELDS - raw_keys
    unknown = raw_keys - _PLUGIN_FIELDS
    if missing or unknown:
        msg = (
            f"Vendor {position} plugin {plugin_label} must contain required fields "
            f"{', '.join(sorted(_PLUGIN_REQUIRED_FIELDS))}"
            f" and may include optional: {', '.join(sorted(_PLUGIN_OPTIONAL_FIELDS))}"
        )
        raise ValueError(msg)
    plugin_id = _required_string(
        value=raw_plugin["id"],
        field="id",
        position=position,
    )
    if _ID_PATTERN.fullmatch(plugin_id) is None:
        msg = f"Vendor {position} plugin {plugin_id} id must be a lowercase slug"
        raise ValueError(msg)
    description = _required_string(
        value=raw_plugin["description"],
        field="description",
        position=position,
    )
    skills_root = _parse_relative_posix_path(
        value=raw_plugin["skillsRoot"],
        field="skillsRoot",
        position=position,
        plugin_id=plugin_id,
    )
    skills = _parse_plugin_skills(
        value=raw_plugin["skills"],
        position=position,
        plugin_id=plugin_id,
    )
    extra_skills = _parse_optional_path_list(
        value=raw_plugin.get("extraSkills", []),
        field="extraSkills",
        position=position,
        plugin_id=plugin_id,
    )
    rename_skills = _parse_rename_skills(
        value=raw_plugin.get("renameSkills", {}),
        position=position,
        plugin_id=plugin_id,
    )
    agents = _parse_plugin_agents(
        value=raw_plugin.get("agents"),
        position=position,
        plugin_id=plugin_id,
    )
    return VendorPlugin(
        id=plugin_id,
        description=description,
        skills_root=skills_root,
        skills=skills,
        extra_skills=extra_skills,
        rename_skills=rename_skills,
        agents=agents,
    )


def _parse_plugin_skills(
    *,
    value: object,
    position: int,
    plugin_id: str,
) -> str | tuple[str, ...]:
    """Validate ``skills: "*"`` or a non-empty list of relative paths.

    Args:
        value: Raw YAML ``skills`` value.
        position: One-based vendor position.
        plugin_id: Plugin id for error messages.

    Returns:
        ``"*"`` or a tuple of paths relative to ``skillsRoot``.

    Raises:
        TypeError: If ``skills`` is neither a string nor a list of strings.
        ValueError: If the selector is empty or uses unsafe paths.
    """
    where = _plugin_where(position=position, plugin_id=plugin_id)
    if value == "*":
        return "*"
    if not isinstance(value, list) or not value:
        msg = f'{where} skills must be "*" or a non-empty list of relative paths'
        raise ValueError(msg)
    paths = tuple(
        _parse_relative_posix_path(
            value=path,
            field="skills",
            position=position,
            plugin_id=plugin_id,
        )
        for path in value
    )
    if len(paths) != len(set(paths)):
        msg = f"{where} skills paths must be unique"
        raise ValueError(msg)
    return paths


def _parse_optional_path_list(
    *,
    value: object,
    field: str,
    position: int,
    plugin_id: str,
) -> tuple[str, ...]:
    """Validate an optional list of relative POSIX paths.

    Args:
        value: Raw YAML list value.
        field: Field name for error messages.
        position: One-based vendor position.
        plugin_id: Plugin id for error messages.

    Returns:
        Validated relative paths.

    Raises:
        TypeError: If the value is not a list of strings.
        ValueError: If a path is unsafe or duplicated.
    """
    where = _plugin_where(position=position, plugin_id=plugin_id)
    if not isinstance(value, list):
        msg = f"{where} {field} must be a list"
        raise TypeError(msg)
    paths = tuple(
        _parse_relative_posix_path(
            value=path,
            field=field,
            position=position,
            plugin_id=plugin_id,
        )
        for path in value
    )
    if len(paths) != len(set(paths)):
        msg = f"{where} {field} entries must be unique"
        raise ValueError(msg)
    return paths


def _parse_rename_skills(
    *,
    value: object,
    position: int,
    plugin_id: str,
) -> tuple[tuple[str, str], ...]:
    """Validate reviewed skill-directory renames.

    Args:
        value: Raw YAML ``renameSkills`` mapping.
        position: One-based vendor position.
        plugin_id: Plugin id for error messages.

    Returns:
        Ordered ``(old, new)`` kebab-case pairs.

    Raises:
        TypeError: If the value is not a string mapping.
        ValueError: If a name is not kebab-case, is identity, or collides.
    """
    where = _plugin_where(position=position, plugin_id=plugin_id)
    if not isinstance(value, dict):
        msg = f"{where} renameSkills must be a mapping"
        raise TypeError(msg)
    pairs: list[tuple[str, str]] = []
    for raw_old, raw_new in value.items():
        if not isinstance(raw_old, str) or not isinstance(raw_new, str):
            msg = f"{where} renameSkills keys and values must be strings"
            raise TypeError(msg)
        old = raw_old.strip()
        new = raw_new.strip()
        if _ID_PATTERN.fullmatch(old) is None or _ID_PATTERN.fullmatch(new) is None:
            msg = f"{where} renameSkills keys and values must be lowercase slugs"
            raise ValueError(msg)
        if old == new:
            msg = f"{where} renameSkills must change the skill name"
            raise ValueError(msg)
        pairs.append((old, new))
    targets = [new for _, new in pairs]
    if len(targets) != len(set(targets)):
        msg = f"{where} renameSkills targets must be unique"
        raise ValueError(msg)
    return tuple(pairs)


def _parse_plugin_agents(
    *,
    value: object,
    position: int,
    plugin_id: str,
) -> tuple[str, ...]:
    """Validate an optional list of known host agent names.

    Args:
        value: Raw YAML ``agents`` value, or ``None`` when omitted.
        position: One-based vendor position.
        plugin_id: Plugin id for error messages.

    Returns:
        Unique known agent names in source order.

    Raises:
        TypeError: If ``agents`` is not a string list.
        ValueError: If the list is empty, duplicated, or names an unknown host.
    """
    if value is None:
        return ()
    where = _plugin_where(position=position, plugin_id=plugin_id)
    if not isinstance(value, list) or not value:
        msg = f"{where} agents must be a non-empty list"
        raise ValueError(msg)
    agents: list[str] = []
    for raw_agent in value:
        if not isinstance(raw_agent, str):
            msg = f"{where} agents entries must be strings"
            raise TypeError(msg)
        agent = raw_agent.strip()
        if agent not in _KNOWN_HOST_AGENTS:
            msg = (
                f"{where} agents entries must be one of: "
                f"{', '.join(sorted(_KNOWN_HOST_AGENTS))}"
            )
            raise ValueError(msg)
        agents.append(agent)
    if len(agents) != len(set(agents)):
        msg = f"{where} agents entries must be unique"
        raise ValueError(msg)
    return tuple(agents)


def _validate_plugin_id_uniqueness(
    *,
    vendors: tuple[Vendor, ...],
    registry_path: Path,
) -> None:
    """Reject vendor plugin ids that collide with each other or first-party ids.

    Args:
        vendors: Validated vendor records.
        registry_path: Path to ``vendors.yaml``; sibling ``bundles.yaml``
            supplies first-party plugin ids when present.

    Raises:
        ValueError: If a plugin id is duplicated or collides with a bundle id.
    """
    first_party = _first_party_plugin_ids(registry_path=registry_path)
    seen: dict[str, str] = {}
    for vendor in vendors:
        for plugin in vendor.plugins:
            if plugin.id in first_party:
                msg = (
                    f"Vendor plugin id {plugin.id!r} collides with a "
                    "first-party plugin id"
                )
                raise ValueError(msg)
            owner = seen.get(plugin.id)
            if owner is not None:
                msg = (
                    f"Vendor plugin ids must be unique across vendors: "
                    f"{plugin.id!r} is declared by {owner} and {vendor.id}"
                )
                raise ValueError(msg)
            seen[plugin.id] = vendor.id


def _first_party_plugin_ids(*, registry_path: Path) -> frozenset[str]:
    """Read kebab-case plugin ids from sibling ``bundles.yaml`` when present.

    Args:
        registry_path: Path to ``vendors.yaml``.

    Returns:
        First-party plugin ids, or empty when ``bundles.yaml`` is absent.

    Raises:
        ValueError: If ``bundles.yaml`` exists but is not a mapping of groups.
    """
    bundles_path = registry_path.parent / "bundles.yaml"
    if not bundles_path.is_file():
        return frozenset()
    data = yaml.safe_load(bundles_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "groups" not in data:
        msg = "bundles.yaml must contain a 'groups' mapping"
        raise ValueError(msg)
    groups = data["groups"]
    if groups is None:
        return frozenset()
    if not isinstance(groups, dict):
        msg = "bundles.yaml 'groups' must be a mapping"
        raise TypeError(msg)
    ids: set[str] = set()
    for group in groups.values():
        if not isinstance(group, dict):
            continue
        plugin_id = group.get("id")
        if isinstance(plugin_id, str) and plugin_id:
            ids.add(plugin_id)
    return frozenset(ids)


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
