"""Read-only author inventory command."""

import argparse
import sys
from contextlib import redirect_stdout
from pathlib import Path

from ai_skills_engine.inventory.load import load_inventory
from ai_skills_engine.paths import resolve_repo_root


def vendor_roots(values: list[str]) -> dict[str, Path]:
    """Parse explicit offline snapshots without altering their contents.

    Args:
        values: ID=PATH arguments.

    Returns:
        Alias to local path mapping.

    Raises:
        ValueError: On empty or duplicate aliases/paths.
    """
    roots: dict[str, Path] = {}
    for value in values:
        name, separator, path = value.partition("=")
        if not separator or not name or not path or name in roots:
            raise ValueError("--vendor-root requires unique ID=PATH arguments")
        roots[name] = Path(path)
    return roots


def main(argv: list[str] | None = None) -> int:
    """Print records and diagnostics, returning failure for any observed error.

    Args:
        argv: Command arguments.

    Returns:
        Zero when there are no error diagnostics, one otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--vendor-root", action="append", default=[], metavar="ID=PATH")
    parser.add_argument(
        "--fetch-vendors",
        action="store_true",
        help="Explicitly fetch missing SHA-pinned vendor inputs via the bake fetcher",
    )
    args = parser.parse_args(argv)
    try:
        # The shared bake fetcher reports acquisition notes. Keep JSON stdout
        # exclusively machine-readable while preserving those notes on stderr.
        with redirect_stdout(sys.stderr):
            inventory = load_inventory(
                resolve_repo_root(override=args.repo_root, parser=parser),
                vendor_roots=vendor_roots(args.vendor_root),
                fetch_vendors=args.fetch_vendors,
            )
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"inventory: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(inventory.to_json(), end="")
    else:
        for capability in inventory.capabilities:
            print(f"{capability.id} [{capability.dialect}] {capability.source_path}")
        for resource in inventory.resources:
            print(f"{resource.id} {resource.source_path}")
        for item in inventory.diagnostics:
            severity = "warning" if item.warning else "error"
            print(f"{severity} {item.code} {item.location}: {item.message}")
    return int(any(not item.warning for item in inventory.diagnostics))
