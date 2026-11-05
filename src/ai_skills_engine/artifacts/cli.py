"""``bake artifacts``: write artifacts from explicitly supplied local inputs.

This development writer never consults, writes or fetches for the resolution
lock. ``ai-skills-engine lock`` records reviewed digests and
``ai-skills-engine build`` rebuilds them offline from the lock and cache.
"""

import argparse
import sys
from pathlib import Path

from ai_skills_engine.artifact import build
from ai_skills_engine.inventory.cli import vendor_roots
from ai_skills_engine.paths import resolve_repo_root
from ai_skills_engine.registry.ingest_checks import safe_diagnostic


def main(argv: list[str] | None = None) -> int:
    """Write artifacts from the manifest and explicit offline vendor snapshots.

    Args:
        argv: Explicit command arguments.

    Returns:
        Zero for a successful build; one for input errors.
    """
    parser = argparse.ArgumentParser(
        prog="ai-skills-engine bake artifacts", description=__doc__
    )
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument(
        "--vendor-root", "--vendor-tree", action="append", default=[], metavar="ID=PATH"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    root = resolve_repo_root(override=args.repo_root, parser=parser).resolve()
    try:
        build(
            root=root,
            vendor_roots=vendor_roots(args.vendor_root),
            destination=args.output,
        )
        return 0
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as error:
        print("artifacts: " + safe_diagnostic(str(error)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
