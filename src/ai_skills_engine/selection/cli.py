"""Read-only offline build-plane plan command."""

import argparse
from pathlib import Path

from ai_skills_engine.inventory.cli import vendor_roots
from ai_skills_engine.paths import resolve_repo_root
from ai_skills_engine.selection.diagnostic import SelectionDiagnostic
from ai_skills_engine.selection.explain import explain
from ai_skills_engine.selection.load import load_selection
from ai_skills_engine.selection.model import SelectionResult


def main(argv: list[str] | None = None) -> int:
    """Print the complete explain trace; never write locks or installed output.

    Args:
        argv: Command arguments.

    Returns:
        Zero for valid plans, one for any diagnostic error.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--vendor-root", action="append", default=[], metavar="ID=PATH")
    args = parser.parse_args(argv)
    root = resolve_repo_root(override=args.repo_root, parser=parser)
    try:
        result = load_selection(root, vendor_roots=vendor_roots(args.vendor_root))
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        result = SelectionResult(
            capabilities=(),
            resources=(),
            diagnostics=(
                SelectionDiagnostic(
                    code="selection.invalid-input",
                    location="manifest",
                    message=str(error).replace(str(root), "."),
                    chain=(),
                    fix=(
                        "Repair the manifest schema/selectors and provide "
                        "complete offline vendor inputs."
                    ),
                ),
            ),
        )
    print(result.to_json() if args.json else explain(result), end="")
    return int(not result.valid)
