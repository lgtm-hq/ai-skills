"""Hash protected host configuration without printing any file contents.

Run before changing HOME. Write snapshots outside the repository, compare them
locally, and publish only counts and the aggregate digest. Runtime transcripts,
databases, logs and other session output at known host runtime roots are outside
this inventory. Identically named directories inside payloads remain protected.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# These are direct children of each host root, never arbitrary path components.
# .agents has no known runtime roots to exclude.
HOST_RUNTIME_ROOTS = {
    ".claude": {
        "projects",
        "debug",
        "telemetry",
        "backups",
        "tmp",
        "session-env",
        "todos",
        "paste-cache",
        "file-history",
        "plans",
    },
    ".codex": {"sessions", "logs", "log", "shell_snapshots", "tmp"},
    ".cursor": {"logs", "projects"},
}
CONFIG_SUFFIXES = {".json", ".jsonc", ".toml", ".yaml", ".yml", ".md"}


def snapshot(home: Path) -> dict[str, dict[str, str | int | bool]]:
    """Inventory config paths, mtimes and hashes under the supplied home.

    Args:
        home: Home directory whose configuration is protected.

    Returns:
        Home-relative paths paired with metadata, never file contents.
    """
    records: dict[str, dict[str, str | int | bool]] = {}
    for name in (".claude", ".codex", ".cursor", ".agents"):
        base = home / name
        if not base.exists():
            records[f"~/{name}"] = {"absent": True}
            continue
        for path in sorted(base.rglob("*")):
            relative = path.relative_to(base)
            if relative.parts[0] in HOST_RUNTIME_ROOTS.get(name, set()):
                continue
            if path.is_file() and (
                path.suffix in CONFIG_SUFFIXES or path.name in {"auth", "credentials"}
            ):
                records[f"~/{name}/{relative.as_posix()}"] = {
                    "mtime_ns": path.stat().st_mtime_ns,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
    extra = home / ".claude.json"
    if extra.is_file():
        records["~/.claude.json"] = {
            "mtime_ns": extra.stat().st_mtime_ns,
            "sha256": hashlib.sha256(extra.read_bytes()).hexdigest(),
        }
    return records


def main() -> None:
    """Write the private inventory and print only its count and digest."""
    destination = Path(sys.argv[1])
    data = snapshot(Path.home())
    destination.write_text(
        json.dumps(data, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "files": len(data),
                "snapshot_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            },
        ),
    )


if __name__ == "__main__":
    main()
