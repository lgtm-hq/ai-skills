#!/usr/bin/env python3
"""Audit ai-skills' adoption of lgtm-ci reusable workflows.

Compares the reusable workflows available in ``lgtm-hq/lgtm-ci`` at the
SHA this repository pins against the reusable workflows this
repository's workflows actually call.

The pinned SHA is discovered by scanning ``.github/workflows/*.yml`` for
``uses: lgtm-hq/lgtm-ci/.github/workflows/<name>@<sha>`` lines. The
available set is fetched via ``gh api`` (so the script is CI-runnable
and needs no local lgtm-ci checkout).

``reusable-ai-review.yml`` may pin a newer published contract than the
rest of the repo (the current caller contract landed after the shared
quality/release SHA). ``reusable-scorecards.yml`` was held on an older
SHA for lgtm-hq/lgtm-ci#1173 (fixed in v0.77.6) and is still tolerated
on its own SHA until that exception is removed. Repo-wide uniqueness
excludes those names. Pins *inside* each of them must still be a single SHA.

Output: three sections — the pinned ref, adopted workflows, and
available-but-unadopted workflows — plus summary counts.

Exit codes: ``0`` on success, ``2`` on operational error (no pin found,
mixed pins, or ``gh`` failure).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404 - fixed gh argv list, no shell
import sys
from pathlib import Path

LGTM_CI_REPO = "lgtm-hq/lgtm-ci"
AI_REVIEW_WORKFLOW = "reusable-ai-review.yml"
SCORECARDS_WORKFLOW = "reusable-scorecards.yml"
# Workflows allowed to pin a different SHA than the shared one.
# TODO(#534): scorecards.yml is back on the shared SHA (lgtm-ci#1173 is
# fixed); drop SCORECARDS_WORKFLOW and its tests.
INDEPENDENT_PIN_WORKFLOWS = frozenset(
    {AI_REVIEW_WORKFLOW, SCORECARDS_WORKFLOW},
)

_USES_RE = re.compile(
    r"uses:\s*lgtm-hq/lgtm-ci/\.github/workflows/(?P<name>[\w.-]+\.ya?ml)"
    r"@(?P<ref>[0-9a-f]{40})",
)
_TOOLING_REF_RE = re.compile(
    r"""tooling-ref:\s*["']?(?P<ref>[0-9a-f]{40})["']?""",
)


def find_lgtm_ci_pins(
    workflows_dir: Path,
) -> dict[str, set[str]]:
    """Find lgtm-ci reusable-workflow calls in local workflow files.

    Args:
        workflows_dir: Directory containing this repository's workflow
            YAML files (typically ``.github/workflows``).

    Returns:
        Mapping of called lgtm-ci workflow file name to the set of
        40-char SHAs it is pinned at across all callers. Multiple SHAs
        for one name are preserved so mixed pins are not collapsed.
    """
    pins: dict[str, set[str]] = {}
    workflow_paths = sorted(
        {
            *workflows_dir.glob("*.yml"),
            *workflows_dir.glob("*.yaml"),
        },
    )
    for path in workflow_paths:
        for match in _USES_RE.finditer(path.read_text(encoding="utf-8")):
            pins.setdefault(match.group("name"), set()).add(match.group("ref"))
    return pins


def resolve_pinned_ref(
    pins: dict[str, set[str]],
    exclude: frozenset[str] = frozenset(),
) -> str:
    """Resolve the single SHA this repository pins lgtm-ci at.

    Args:
        pins: Mapping of workflow name to pinned SHA set, as returned by
            :func:`find_lgtm_ci_pins`.
        exclude: Workflow names omitted from the uniqueness check so
            they can pin a different SHA than the rest of the repo
            (see ``INDEPENDENT_PIN_WORKFLOWS``).

    Returns:
        The common pinned SHA of non-excluded callers. If every caller
        is excluded (for example ``reusable-ai-review.yml`` is the only
        pin), the lowest excluded SHA is returned so the tree still
        produces a report; excluded callers may pin different SHAs, and
        :func:`main` reports each one that differs separately.

    Raises:
        ValueError: If no lgtm-ci calls were found, or if the
            non-excluded callers pin more than one distinct SHA.
    """
    refs = sorted(
        {
            ref
            for name, ref_set in pins.items()
            if name not in exclude
            for ref in ref_set
        },
    )
    if not refs:
        excluded_refs = sorted(
            {
                ref
                for name, ref_set in pins.items()
                if name in exclude
                for ref in ref_set
            },
        )
        if excluded_refs:
            return excluded_refs[0]
        msg = "no lgtm-ci reusable-workflow calls found"
        raise ValueError(msg)
    if len(refs) > 1:
        msg = f"mixed lgtm-ci pins found: {', '.join(refs)}"
        raise ValueError(msg)
    return refs[0]


def assert_single_pin_per_name(
    pins: dict[str, set[str]],
    name: str,
) -> None:
    """Raise if one reusable workflow name is pinned at two SHAs.

    Args:
        pins: Mapping of workflow name to pinned SHA set.
        name: Reusable workflow file name to inspect.

    Raises:
        ValueError: If ``name`` has more than one SHA.
    """
    refs = pins.get(name, set())
    if len(refs) > 1:
        joined = ", ".join(sorted(refs))
        msg = f"mixed lgtm-ci pins inside {name}: {joined}"
        raise ValueError(msg)


def assert_uses_tooling_ref_lockstep(
    workflows_dir: Path,
) -> None:
    """Raise if a caller file pins ``uses`` and ``tooling-ref`` differently.

    Args:
        workflows_dir: Directory containing this repository's workflow
            YAML files.

    Raises:
        ValueError: If a ``reusable-ai-review.yml`` caller has ``uses``
            but no ``tooling-ref``, or if any file has both pins and
            they are not the same set of SHAs.
    """
    workflow_paths = sorted(
        {
            *workflows_dir.glob("*.yml"),
            *workflows_dir.glob("*.yaml"),
        },
    )
    for path in workflow_paths:
        text = path.read_text(encoding="utf-8")
        uses_matches = list(_USES_RE.finditer(string=text))
        uses = {match.group("ref") for match in uses_matches}
        names = {match.group("name") for match in uses_matches}
        tooling = set(_TOOLING_REF_RE.findall(string=text))
        if AI_REVIEW_WORKFLOW in names and not tooling:
            msg = (
                f"{path.name}: {AI_REVIEW_WORKFLOW} requires tooling-ref "
                "in lockstep with uses"
            )
            raise ValueError(msg)
        if not tooling:
            continue
        if uses != tooling:
            msg = (
                f"{path.name}: uses and tooling-ref pins differ: "
                f"{sorted(uses)} vs {sorted(tooling)}"
            )
            raise ValueError(msg)


def list_available_workflows(
    ref: str,
) -> list[str]:
    """List reusable workflows available in lgtm-ci at a given ref.

    Args:
        ref: Git ref (SHA, branch, or tag) of lgtm-ci to inspect.

    Returns:
        Sorted file names of ``reusable-*.yml`` workflows at that ref.

    Raises:
        RuntimeError: If the ``gh api`` call fails.
    """
    result = subprocess.run(  # nosec B603 B607 - fixed gh argv
        [
            "gh",
            "api",
            f"repos/{LGTM_CI_REPO}/contents/.github/workflows?ref={ref}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        msg = f"gh api failed: {result.stderr.strip()}"
        raise RuntimeError(msg)
    entries = json.loads(result.stdout)
    return sorted(
        entry["name"]
        for entry in entries
        if entry["name"].startswith("reusable-")
        and entry["name"].endswith((".yml", ".yaml"))
    )


def build_report(
    available: list[str],
    called: set[str],
) -> str:
    """Build the adopted/unadopted report text.

    Args:
        available: Reusable workflow file names available upstream.
        called: Workflow file names this repository calls.

    Returns:
        Human-readable report with adopted and available-unadopted
        sections plus summary counts.
    """
    adopted = [name for name in available if name in called]
    unadopted = [name for name in available if name not in called]
    lines: list[str] = []
    lines.append(f"Adopted ({len(adopted)}):")
    lines.extend(f"  {name}" for name in adopted)
    lines.append("")
    lines.append(f"Available, unadopted ({len(unadopted)}):")
    lines.extend(f"  {name}" for name in unadopted)
    lines.append("")
    lines.append(
        f"Summary: {len(adopted)}/{len(available)} available reusable "
        f"workflows adopted.",
    )
    return "\n".join(lines)


def _parse_args(
    argv: list[str],
) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list (excluding the program name).

    Returns:
        The parsed namespace with a ``workflows_dir`` attribute.
    """
    parser = argparse.ArgumentParser(
        description="Audit ai-skills' adoption of lgtm-ci reusable workflows.",
    )
    parser.add_argument(
        "--workflows-dir",
        type=Path,
        default=Path(".github/workflows"),
        help="Directory containing this repo's workflow YAML files.",
    )
    return parser.parse_args(args=argv)


def main(
    argv: list[str] | None = None,
) -> int:
    """Run the adoption audit and print the report.

    Args:
        argv: Argument list (excluding the program name); defaults to
            ``sys.argv[1:]``.

    Returns:
        Process exit code: ``0`` on success, ``2`` on operational error.
    """
    args = _parse_args(argv=sys.argv[1:] if argv is None else argv)
    pins = find_lgtm_ci_pins(workflows_dir=args.workflows_dir)
    extra_refs: dict[str, str] = {}
    try:
        for name in sorted(INDEPENDENT_PIN_WORKFLOWS):
            assert_single_pin_per_name(pins=pins, name=name)
        assert_uses_tooling_ref_lockstep(workflows_dir=args.workflows_dir)
        ref = resolve_pinned_ref(
            pins=pins,
            exclude=INDEPENDENT_PIN_WORKFLOWS,
        )
        available = set(list_available_workflows(ref=ref))
        for name in sorted(INDEPENDENT_PIN_WORKFLOWS):
            name_refs = pins.get(name, set())
            if len(name_refs) != 1:
                continue
            name_ref = next(iter(name_refs))
            if name_ref == ref:
                continue
            extra_refs[name] = name_ref
            if name in list_available_workflows(ref=name_ref):
                available.add(name)
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"lgtm-ci pinned ref: {ref}")
    for name, name_ref in extra_refs.items():
        print(f"{name} pinned ref: {name_ref}")
    print()
    print(build_report(available=sorted(available), called=set(pins)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
