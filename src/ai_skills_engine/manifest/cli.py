"""Author manifest validate/migrate/legacy command entry points."""

import argparse
from collections.abc import Callable
from pathlib import Path

from ai_skills_engine.manifest.legacy import write_legacy
from ai_skills_engine.manifest.load import load_consumer, read_document
from ai_skills_engine.manifest.migrate import migrate
from ai_skills_engine.manifest.terminology import lint_terminology
from ai_skills_engine.paths import resolve_repo_root


def _run(
    argv: list[str] | None,
    *,
    action: str,
    operation: Callable[[Path, argparse.Namespace], int],
) -> int:
    """Parse common root arguments and translate declaration errors to exit 1.

    Args:
        argv: Remaining command arguments.
        action: Manifest subcommand.
        operation: Selected author operation.

    Returns:
        Operation's exit status.
    """
    parser = argparse.ArgumentParser(description=f"manifest {action}")
    parser.add_argument("--repo-root", type=Path)
    if action == "validate":
        parser.add_argument("--terminology", action="store_true")
        parser.add_argument(
            "--vendor-root",
            action="append",
            default=[],
            metavar="ID=PATH",
            help="Explicit offline vendor checkout (no fetching)",
        )
    if action == "legacy":
        parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        return operation(
            resolve_repo_root(override=args.repo_root, parser=parser), args
        )
    except (OSError, TypeError, ValueError) as error:
        print(f"manifest {action}: {error}")
        return 1


def validate(argv: list[str] | None = None) -> int:
    """Validate the manifest, optionally with docs terminology and local vendors.

    Args:
        argv: CLI arguments.

    Returns:
        Zero for valid input, one for any error diagnostic.
    """

    def operation(root: Path, args: argparse.Namespace) -> int:
        """Validate offline declarations and report warnings separately."""
        roots = {}
        for item in args.vendor_root:
            name, separator, path = item.partition("=")
            if not separator:
                raise ValueError("--vendor-root requires ID=PATH")
            roots[name] = Path(path)
        _, _, diagnostics = load_consumer(root / "ai-skills.yaml", vendor_roots=roots)
        findings = list(diagnostics)
        if args.terminology:
            findings.extend(
                lint_terminology(root, read_document(root / "ai-skills.yaml"))
            )
        for finding in findings:
            severity = "warning" if finding.warning else "error"
            print(f"{severity} {finding.code} {finding.location}: {finding.message}")
        return int(any(not item.warning for item in findings))

    return _run(argv, action="validate", operation=operation)


def migration(argv: list[str] | None = None) -> int:
    """Create a manifest once from the repository's old registries.

    Args:
        argv: CLI arguments.

    Returns:
        Zero on successful migration.
    """

    def operation(root: Path, args: argparse.Namespace) -> int:
        """Perform the one-shot migration."""
        del args
        migrate(root)
        return 0

    return _run(argv, action="migrate", operation=operation)


def legacy(argv: list[str] | None = None) -> int:
    """Generate legacy files or check deterministic bytes for drift.

    Args:
        argv: CLI arguments.

    Returns:
        Legacy generator status.
    """
    return _run(
        argv,
        action="legacy",
        operation=lambda root, args: write_legacy(root, check=args.check),
    )
