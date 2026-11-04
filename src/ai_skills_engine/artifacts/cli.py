"""Offline artifact build and reviewed-digest verification commands."""

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_skills_engine.artifact import DIGEST_FILENAME, build
from ai_skills_engine.artifacts.acquire import acquire_inputs
from ai_skills_engine.artifacts.drift import (
    check_inputs,
    compare_digests,
    inputs_digest,
)
from ai_skills_engine.artifacts.format import canonical_json
from ai_skills_engine.inventory.cli import vendor_roots
from ai_skills_engine.paths import resolve_repo_root
from ai_skills_engine.registry.ingest_checks import safe_diagnostic


def main(argv: list[str] | None = None) -> int:
    """Build artifacts or regenerate/check the reviewed digest commitment.

    Args:
        argv: Explicit command arguments.

    Returns:
        Zero for a successful build/check; one for input errors or drift.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument(
        "--vendor-root", "--vendor-tree", action="append", default=[], metavar="ID=PATH"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--digests", type=Path)
    parser.add_argument(
        "--fetch-vendors",
        action="store_true",
        help="Explicitly acquire missing manifest-pinned build inputs",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--write-digests", action="store_true")
    modes.add_argument(
        "--check",
        action="store_true",
        help="Rebuild in private scratch and compare all reviewed digests",
    )
    modes.add_argument(
        "--check-inputs",
        action="store_true",
        help="Offline checkout drift check; publishing must also rebuild",
    )
    args = parser.parse_args(argv)
    root = resolve_repo_root(override=args.repo_root, parser=parser).resolve()
    try:
        path = args.digests or root / DIGEST_FILENAME
        if args.check_inputs:
            return int(not check_inputs(root=root, path=path))
        roots = vendor_roots(args.vendor_root)
        with TemporaryDirectory(prefix="ai-skills-artifacts-check-") as temporary:
            if args.fetch_vendors:
                roots = acquire_inputs(
                    root=root, supplied=roots, temporary=Path(temporary) / "inputs"
                )
            output = Path(temporary) / "artifacts" if args.check else args.output
            result = build(root=root, vendor_roots=roots, destination=output)
            result["inputsDigest"] = inputs_digest(root)
            if args.check:
                return int(not compare_digests(expected=result, path=path))
            if args.write_digests:
                path.write_bytes(canonical_json(result))
        return 0
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as error:
        print("artifacts: " + safe_diagnostic(str(error)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
