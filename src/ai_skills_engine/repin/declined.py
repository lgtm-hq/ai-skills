"""Re-pin PR marker and declined-revision lookup.

Every re-pin body ends with ``<!-- ai-skills-repin vendor=<id> revision=<sha> -->``.
A closed, unmerged PR carrying the marker for the same vendor and revision means
a human declined that revision; re-pinning to it again is skipped. A newer
revision is not suppressed.
"""

import json
import re
import shutil
import subprocess  # nosec B404 - fixed gh argv list, no shell
import sys
from collections.abc import Callable, Iterable, Mapping
from typing import Any

MARKER_PREFIX = "<!-- ai-skills-repin "
_MARKER = re.compile(
    r"<!-- ai-skills-repin vendor=(?P<vendor>[a-z0-9]+(?:-[a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:-[a-z0-9]+)*)*) revision=(?P<revision>[0-9a-f]{40}) -->"
)
_LIST_LIMIT = "200"
type GhRunner = Callable[[list[str]], str]


def marker(*, vendor: str, revision: str) -> str:
    """Render the machine-readable PR marker.

    Args:
        vendor: Consumer vendor alias.
        revision: Target 40-hex revision.

    Returns:
        HTML comment identifying the re-pin.
    """
    return f"<!-- ai-skills-repin vendor={vendor} revision={revision} -->"


def markers(text: str) -> set[tuple[str, str]]:
    """Parse every re-pin marker in a body or comment.

    Args:
        text: Markdown text.

    Returns:
        ``(vendor, revision)`` pairs.
    """
    return {
        (match.group("vendor"), match.group("revision"))
        for match in _MARKER.finditer(text)
    }


def _texts(pull: Mapping[str, Any]) -> Iterable[str]:
    """Yield the body and comment bodies of one listed PR.

    Args:
        pull: ``gh pr list --json`` record.

    Yields:
        Markdown texts that may carry a marker.
    """
    body = pull.get("body")
    if isinstance(body, str):
        yield body
    for comment in pull.get("comments") or ():
        if isinstance(comment, dict) and isinstance(comment.get("body"), str):
            yield comment["body"]


def run_gh(argv: list[str]) -> str:
    """Run a read-only ``gh`` query.

    Args:
        argv: Arguments after ``gh``.

    Returns:
        Standard output.

    Raises:
        RuntimeError: If ``gh`` is unavailable or fails.
    """
    executable = shutil.which("gh")
    if executable is None:
        raise RuntimeError("gh is required for --skip-declined")
    try:
        return subprocess.run(  # nosec B603 - fixed read-only gh argv
            [executable, *argv],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"gh pr list failed with status {error.returncode}"
        ) from error


def declined_pr(
    *, vendor: str, revision: str, runner: GhRunner | None = None
) -> int | None:
    """Find a closed, unmerged re-pin PR that declined this exact revision.

    Args:
        vendor: Consumer vendor alias.
        revision: Candidate revision.
        runner: ``gh`` runner; tests inject a fake.

    Returns:
        Lowest declining PR number, or None when the revision was not declined.

    Raises:
        TypeError: If ``gh`` returns something other than a JSON list.
    """
    output = (runner or run_gh)(
        [
            "pr",
            "list",
            "--state",
            "closed",
            "--limit",
            _LIST_LIMIT,
            "--json",
            "number,mergedAt,body,comments",
        ]
    )
    pulls = json.loads(output)
    if not isinstance(pulls, list):
        raise TypeError("gh pr list did not return a JSON list")
    if len(pulls) >= int(_LIST_LIMIT):
        print(
            f"repin: --skip-declined read only the {_LIST_LIMIT} most recent "
            "closed PRs; a revision declined in an older PR is not skipped",
            file=sys.stderr,
        )
    found = [
        int(pull["number"])
        for pull in pulls
        if isinstance(pull, dict)
        and not pull.get("mergedAt")
        and any((vendor, revision) in markers(text) for text in _texts(pull))
    ]
    return min(found) if found else None
