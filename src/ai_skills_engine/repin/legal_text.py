"""Compare license and notice text without the revision-only header.

Generated ``LICENSES/<origin>.txt`` files start every ``(origin, revision)``
section with an ``Origin:``/``Revision:``/``Declared license:`` header, so their
digests move on every pin bump even when the license text is byte-identical.
Re-pin compares legal content with exactly that ``Revision:`` header line
removed; the artifact bytes and the index contract are untouched.
"""

import hashlib
import re
from collections.abc import Iterable

# The exact header written by ``artifacts.legal.legal_files`` for one section.
_REVISION_HEADER = re.compile(
    rb"^(Origin: [^\n]*\n)Revision: [^\n]*\n(?=Declared license: )",
    flags=re.MULTILINE,
)


def is_legal(path: str) -> bool:
    """Tell whether an artifact member is a generated legal file.

    Args:
        path: Artifact member path.

    Returns:
        True for ``NOTICE.md`` and ``LICENSES/*`` members.
    """
    return path == "NOTICE.md" or path.startswith("LICENSES/")


def revision_free(*, path: str, data: bytes) -> bytes:
    """Drop the revision-only header lines from one legal file.

    Args:
        path: Artifact member path.
        data: Member bytes.

    Returns:
        ``LICENSES/*`` bytes without their ``Revision:`` header lines; every
        other member unchanged.
    """
    if not path.startswith("LICENSES/"):
        return data
    return _REVISION_HEADER.sub(rb"\1", data)


def content_digest(contents: Iterable[bytes]) -> str:
    """Digest every distinct revision-free content observed for one legal path.

    Package artifacts each carry the legal subset of their own closure, so one
    path can hold several distinct contents across a catalog.

    Args:
        contents: Revision-free contents of the same legal path.

    Returns:
        ``sha256:<hex>`` over the sorted distinct content digests.
    """
    digests = sorted({hashlib.sha256(item).hexdigest() for item in contents})
    return "sha256:" + hashlib.sha256("\n".join(digests).encode()).hexdigest()
