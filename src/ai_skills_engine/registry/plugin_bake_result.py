"""Result record for baking one vendor plugin slice."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PluginBakeResult:
    """Outputs recorded after one plugin slice is written.

    ``ingested_skill_md`` paths are POSIX paths relative to the vendor
    tree. ``explode_names`` are the post-rename skill directory names
    that enter the global explode namespace. ``agent_stems`` are ingested
    ``agents/*.md`` basenames without the suffix.
    """

    plugin_id: str
    version: str
    ingested_skill_md: tuple[str, ...]
    explode_names: tuple[str, ...]
    agent_stems: tuple[str, ...]
    renamed: tuple[tuple[str, str], ...]
