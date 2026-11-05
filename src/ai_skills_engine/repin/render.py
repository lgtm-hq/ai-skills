"""Deterministic Markdown and JSON re-pin bodies.

Sections always appear in the same order, every list is sorted, nothing depends
on time or environment, and file deltas are capped at :data:`FILE_CAP` lines.
The JSON document mirrors the Markdown, including the cap.
"""

import json
from collections.abc import Iterable
from typing import Any

from ai_skills_engine.repin.change import Change
from ai_skills_engine.repin.declined import marker
from ai_skills_engine.repin.report import RepinReport

FILE_CAP = 50


def compare_url(report: RepinReport) -> str | None:
    """Link the upstream diff between the old and new revision.

    Args:
        report: Re-pin report.

    Returns:
        GitHub compare URL, or None without two distinct revisions.
    """
    pin = report.pin
    if pin.old_sha is None or pin.old_sha == pin.new_sha:
        return None
    return f"https://github.com/{pin.repo}/compare/{pin.old_sha}...{pin.new_sha}"


def _lines(items: Iterable[str]) -> list[str]:
    """Render bullets or ``None.``.

    Args:
        items: Rendered bullet bodies.

    Returns:
        Markdown lines.
    """
    rendered = [f"- {item}" for item in items]
    return rendered or ["None."]


def _change(item: Change) -> str:
    """Render one change line.

    Args:
        item: Change.

    Returns:
        Bullet body.
    """
    detail = f" ({item.detail})" if item.detail else ""
    return f"{item.kind} `{item.subject}`{detail}"


def _section(lines: list[str], heading: str, body: list[str]) -> None:
    """Append a headed section.

    Args:
        lines: Accumulator.
        heading: Heading text.
        body: Section lines.
    """
    lines.extend([heading, "", *body, ""])


def _files(report: RepinReport) -> list[str]:
    """Render capped file deltas grouped by capability.

    Args:
        report: Re-pin report.

    Returns:
        Markdown lines.
    """
    shown = report.files[:FILE_CAP]
    if not shown:
        return ["None."]
    lines: list[str] = []
    current = None
    for item in shown:
        if item.subject != current:
            current = item.subject
            lines.append(f"- `{current}`")
        lines.append(f"  - `{item.kind}` `{item.detail}`")
    omitted = len(report.files) - len(shown)
    if omitted:
        lines.append(f"- … {omitted} more file change(s) omitted (cap {FILE_CAP})")
    return lines


def render_markdown(report: RepinReport) -> str:
    """Render the reviewable PR body.

    Args:
        report: Re-pin report.

    Returns:
        Markdown ending with the marker comment and a newline.
    """
    pin = report.pin
    lines = [f"## Vendor re-pin: `{pin.id}`", ""]
    if report.status == "declined":
        lines.extend(
            [
                (
                    f"Skipped: revision `{pin.new_sha}` was declined in a closed, "
                    "unmerged re-pin PR."
                ),
                "",
            ]
        )
        return "\n".join(lines)
    if report.action_required:
        _section(lines, "### Action required", _lines(report.action_required))
    url = compare_url(report)
    _section(
        lines,
        "### Pin",
        [
            f"- Revision: `{pin.old_sha or 'none (new vendor)'}` → `{pin.new_sha}`",
            f"- displayRef: `{pin.display_ref}`",
            f"- Compare: {url or 'n/a'}",
        ],
    )
    if report.status == "unchanged":
        lines.extend(["Pin already current; no bake delta.", "", _marker(report), ""])
        return "\n".join(lines)
    semver = report.semver
    _section(
        lines,
        "### SemVer advice (advisory)",
        (
            ["n/a (no comparison)"]
            if semver is None
            else [f"Level: **{semver.level}**", "", *_lines(semver.reasons)]
        ),
    )
    _section(lines, "### Capabilities", _lines(map(_change, report.capabilities)))
    _section(
        lines,
        "#### Unapplied: identical content at a new ID",
        _lines(
            f"`{item.subject}` → `{item.detail}`" for item in report.unapplied_moves
        ),
    )
    _section(lines, "### Files", _files(report))
    _section(lines, "### Resources", _lines(map(_change, report.resources)))
    _section(lines, "### Lineage", _lines(map(_change, report.lineage)))
    _section(lines, "### License and notice", _lines(map(_change, report.legal)))
    _section(lines, "### Coverage", _lines(map(_change, report.coverage)))
    _section(lines, "### Collisions", _lines(map(_change, report.collisions)))
    _section(
        lines,
        "### Selectors",
        _lines(
            f"`{item.location}` `{item.selector}`: {item.matches} match(es), "
            f"{item.status}" + (f" ({item.detail})" if item.detail else "")
            for item in report.selectors
        ),
    )
    _section(
        lines,
        "### Path drift",
        _lines(
            f"{item.status} `{item.location}` `{item.selector}`: `{item.old_path}`"
            + (
                " → " + ", ".join(f"`{path}`" for path in item.candidates)
                if item.candidates
                else " → no candidate"
            )
            for item in report.drift
        ),
    )
    _section(lines, "### Digests", _lines(map(_change, report.digests)))
    lines.extend([_marker(report), ""])
    return "\n".join(lines)


def _marker(report: RepinReport) -> str:
    """Render the vendor/revision marker.

    Args:
        report: Re-pin report.

    Returns:
        HTML comment.
    """
    return marker(vendor=report.pin.id, revision=report.pin.new_sha)


def to_json(report: RepinReport) -> dict[str, Any]:
    """Mirror the Markdown body as a JSON-compatible mapping.

    Args:
        report: Re-pin report.

    Returns:
        Stable mapping.
    """
    pin = report.pin
    return {
        "vendor": pin.id,
        "repo": pin.repo,
        "status": report.status,
        "actionRequired": list(report.action_required),
        "pin": {
            "old": pin.old_sha,
            "new": pin.new_sha,
            "displayRef": pin.display_ref,
            "compare": compare_url(report),
        },
        "semver": (
            None
            if report.semver is None
            else {"level": report.semver.level, "reasons": list(report.semver.reasons)}
        ),
        "capabilities": [item.to_json() for item in report.capabilities],
        "unappliedMoves": [item.to_json() for item in report.unapplied_moves],
        "files": [item.to_json() for item in report.files[:FILE_CAP]],
        "filesOmitted": max(len(report.files) - FILE_CAP, 0),
        "resources": [item.to_json() for item in report.resources],
        "lineage": [item.to_json() for item in report.lineage],
        "legal": [item.to_json() for item in report.legal],
        "coverage": [item.to_json() for item in report.coverage],
        "collisions": [item.to_json() for item in report.collisions],
        "selectors": [item.to_json() for item in report.selectors],
        "drift": [item.to_json() for item in report.drift],
        "digests": [item.to_json() for item in report.digests],
        "marker": None if report.status == "declined" else _marker(report),
    }


def render_json(report: RepinReport) -> str:
    """Render one report as canonical JSON.

    Args:
        report: Re-pin report.

    Returns:
        Sorted, indented JSON with a trailing newline.
    """
    return (
        json.dumps(to_json(report), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
