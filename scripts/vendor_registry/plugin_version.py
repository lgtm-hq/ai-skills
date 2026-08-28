"""Pin-derived version strings for baked vendor plugins."""

from __future__ import annotations

import re

_SHORT_SHA_LENGTH = 7
_TAG_DISPLAY_REF = re.compile(
    r"^v?\d+\.\d+\.\d+([.-][0-9A-Za-z.]+)?$",
)


def plugin_version(*, sha: str, display_ref: str | None) -> str:
    """Return the bake version stamped onto plugin manifests.

    A consumer-facing semver tag in ``displayRef`` (for example
    ``v1.2.3`` or ``1.2.3-rc.1``) is used as-is. Prefix-only strings
    such as ``v1.2-not-a-version`` are not tags. Floating pins such as
    ``latest``, ``main``, ``master``, ``HEAD``, and a missing display
    ref fall back to the first seven characters of the registry SHA.

    Args:
        sha: 40-character lowercase hex commit SHA from the registry.
        display_ref: Optional consumer-facing pin from ``displayRef``.

    Returns:
        Version string written into generated plugin manifests.
    """
    if display_ref is None or _TAG_DISPLAY_REF.match(display_ref) is None:
        return sha[:_SHORT_SHA_LENGTH]
    return display_ref
