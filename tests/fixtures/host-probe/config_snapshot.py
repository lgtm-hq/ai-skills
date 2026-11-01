"""Hash protected host configuration without printing any file contents.

Run before changing HOME. Write snapshots outside the repository, compare them
locally, and publish only counts and the aggregate digest. Runtime transcripts,
databases, logs and other session output at known host runtime roots are outside
this inventory. Identically named directories inside payloads remain protected.
Links and unreadable paths in the protected scope fail the entire collection.
"""

from __future__ import annotations

import hashlib
import json
import stat
import sys
from collections.abc import Iterator
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


def protected_files(base: Path, excluded: set[str]) -> Iterator[Path]:
    """Yield regular files without following links or hiding traversal errors.

    Args:
        base: Existing host root to inventory.
        excluded: Direct runtime children outside the protected scope.

    Yields:
        Regular files under the host root.

    Raises:
        ValueError: A protected path is a link or unsupported file type.
        OSError: A protected path cannot be listed or inspected.
    """
    pending = [base]
    while pending:
        path = pending.pop()
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError("Snapshot incomplete: linked protected path unsupported")
        if stat.S_ISDIR(mode):
            pending.extend(
                child
                for child in sorted(path.iterdir())
                if path != base or child.name not in excluded
            )
        elif stat.S_ISREG(mode) and path != base:
            yield path
        else:
            raise ValueError("Snapshot incomplete: unsupported protected file type")


def snapshot(home: Path) -> dict[str, dict[str, str | int | bool]]:
    """Inventory config paths, mtimes and hashes under the supplied home.

    Args:
        home: Home directory whose configuration is protected.

    Returns:
        Home-relative paths paired with metadata, never file contents.

    Raises:
        ValueError: HOME, an ancestor or a protected path is linked/unsupported.
        OSError: Inventory traversal or reading fails; never skip the path.
    """
    home = home.absolute()
    for ancestor in (home, *home.parents):
        if stat.S_ISLNK(ancestor.lstat().st_mode):
            raise ValueError("Snapshot incomplete: linked HOME or ancestor unsupported")
    records: dict[str, dict[str, str | int | bool]] = {}
    files: list[Path] = []
    for name in (".claude", ".codex", ".cursor", ".agents"):
        base = home / name
        try:
            base.lstat()
        except FileNotFoundError:
            records[f"~/{name}"] = {"absent": True}
            continue
        files.extend(
            path
            for path in protected_files(
                base=base,
                excluded=HOST_RUNTIME_ROOTS.get(name, set()),
            )
            if path.suffix in CONFIG_SUFFIXES or path.name in {"auth", "credentials"}
        )
    extra = home / ".claude.json"
    try:
        extra_mode = extra.lstat().st_mode
    except FileNotFoundError:
        pass  # This optional config file is genuinely absent, not a dangling link.
    else:
        if not stat.S_ISREG(extra_mode):
            raise ValueError("Snapshot incomplete: unsupported .claude.json path")
        files.append(extra)
    for path in files:
        records[f"~/{path.relative_to(home).as_posix()}"] = {
            "mtime_ns": path.stat().st_mtime_ns,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
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
