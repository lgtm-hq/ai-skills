"""Fetching tracked files from upstream GitHub repositories.

Fetches go through ``raw.githubusercontent.com`` only; repo slugs and
paths are validated first so a malformed ``upstream`` block cannot
redirect the request to another host or path.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request

FETCH_TIMEOUT_SECONDS = 30
RAW_URL_TEMPLATE = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"


def fetch_upstream_text(
    repo: str,
    path: str,
    ref: str = "main",
) -> str:
    """Fetch a file's raw content from a GitHub repository.

    Args:
        repo: Repository slug (``owner/name``).
        path: File path inside the repository.
        ref: Git ref to fetch from; defaults to ``main``.

    Returns:
        The file content decoded as UTF-8.

    Raises:
        RuntimeError: If the repo slug or path is unsafe, the fetch
            fails, or a non-200 status is returned.
    """
    if not re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", repo) or ".." in repo:
        msg = f"Refusing to fetch from suspicious repo slug: {repo!r}"
        raise RuntimeError(msg)
    if path.startswith("/") or ".." in path.split("/"):
        msg = f"Refusing to fetch suspicious upstream path: {path!r}"
        raise RuntimeError(msg)
    url = RAW_URL_TEMPLATE.format(repo=repo, ref=ref, path=path)
    try:
        # nosemgrep - URL template pins scheme and host; repo/path vetted above
        with urllib.request.urlopen(  # noqa: S310 # nosec B310 - host pinned
            url,
            timeout=FETCH_TIMEOUT_SECONDS,
        ) as response:
            content: bytes = response.read()
        return content.decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        msg = f"Failed to fetch {url}: {exc}"
        raise RuntimeError(msg) from exc
