"""``ai-skills-engine install`` / ``update``: consume a resolved artifact.

Both commands verify package digests, subtract excludes and origin denies,
check every kept closure and only then persist the consumer profile. They
never resolve sources, versions or dependency edges. Projection into agent
directories belongs to the destination adapters (#579); this command reports
the kept set those adapters will receive.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from ai_skills_engine.install.errors import InstallError
from ai_skills_engine.install.plan import Command, Plan, Request, plan
from ai_skills_engine.install.profile import default_path, write_profile
from ai_skills_engine.install.selectors import parse_origin, parse_selector
from ai_skills_engine.registry.ingest_checks import safe_diagnostic

ARTIFACTS_ENV = "AI_SKILLS_ARTIFACTS"


def _parser(command: Command) -> argparse.ArgumentParser:
    """Build the shared install/update parser.

    Args:
        command: Command being parsed.

    Returns:
        Configured parser.
    """
    parser = argparse.ArgumentParser(prog=f"ai-skills-engine {command}")
    parser.add_argument(
        "--artifacts", type=Path, help=f"Artifact directory (default: ${ARTIFACTS_ENV})"
    )
    parser.add_argument("--profile", type=Path, help="Consumer profile path")
    parser.add_argument("--repo-root", type=Path, help="Directory with ai-skills.lock")
    parser.add_argument("--digest", action="append", default=[])
    parser.add_argument("--frozen", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--skill", action="append", default=[])
    parser.add_argument("--bundle")
    parser.add_argument("--vendor")
    parser.add_argument("-a", "--agent", action="append", default=[])
    parser.add_argument("-g", "--global", dest="global_scope", action="store_true")
    parser.add_argument("--project", action="store_true")
    parser.add_argument("-y", "--yes", action="store_true")
    if command is Command.INSTALL:
        parser.add_argument("--exclude", action="append", default=[])
        parser.add_argument("--deny-origin", action="append", default=[])
    return parser


def _request(command: Command, args: argparse.Namespace) -> Request:
    """Validate parsed arguments into a request.

    Args:
        command: Command.
        args: Parsed arguments.

    Returns:
        Typed request.

    Raises:
        InstallError: For a missing artifact directory or invalid values.
    """
    if args.global_scope and args.project:
        raise InstallError("Choose only one scope: --global or --project")
    artifacts = args.artifacts or (
        Path(os.environ[ARTIFACTS_ENV]) if os.environ.get(ARTIFACTS_ENV) else None
    )
    if artifacts is None:
        raise InstallError(
            f"no artifact directory; pass --artifacts or ${ARTIFACTS_ENV}"
        )
    return Request(
        command=command,
        artifacts=artifacts,
        profile_path=args.profile or default_path(env=os.environ, home=Path.home()),
        repo_root=args.repo_root or Path.cwd(),
        excludes=tuple(parse_selector(item) for item in getattr(args, "exclude", [])),
        denies=tuple(parse_origin(item) for item in getattr(args, "deny_origin", [])),
        digests=tuple(args.digest),
        frozen=args.frozen,
        skills=tuple(args.skill),
        bundle=args.bundle,
        vendor=args.vendor,
    )


def _report(
    command: Command, result: Plan, *, written: bool, path: Path
) -> dict[str, object]:
    """Describe a plan as JSON-compatible data.

    Args:
        command: Command.
        result: Completed plan.
        written: Whether the profile was written.
        path: Profile path.

    Returns:
        Report document.
    """
    return {
        "command": str(command),
        "packages": [
            {"id": item.id, "digest": item.digest, "pin": str(item.source)}
            for item in result.packages
        ],
        "kept": {
            "capabilities": list(result.result.capabilities),
            "resources": list(result.result.resources),
        },
        "removed": dict(result.result.removed),
        "profile": {"path": str(path), "written": written},
    }


def _print_text(command: Command, result: Plan, *, written: bool, path: Path) -> None:
    """Print the human-readable report, one tab-separated record per line.

    Args:
        command: Command.
        result: Completed plan.
        written: Whether the profile was written.
        path: Profile path.
    """
    for item in result.packages:
        print(f"verified\t{item.id}\t{item.digest}\t{item.source}")
    for key in result.result.capabilities:
        print(f"keep\t{key}")
    for key, reason in result.result.removed.items():
        print(f"remove\t{key}\t{reason}")
    print(f"{command}: profile {'written' if written else 'unchanged'}: {path}")


def run(command: Command, argv: list[str] | None) -> int:
    """Run install or update.

    Args:
        command: Command.
        argv: Command arguments.

    Returns:
        Zero on success, one when the install plane refuses the input.
    """
    args = _parser(command).parse_args(argv)
    try:
        request = _request(command, args)
        result = plan(request)
        written = result.changed and not (args.dry_run or args.frozen)
    except InstallError as error:
        print(f"{command}: {safe_diagnostic(str(error))}", file=sys.stderr)
        return 1
    if written:
        try:
            write_profile(request.profile_path, result.profile)
        except OSError as error:
            message = f"cannot write profile {request.profile_path}: {error}"
            print(f"{command}: {safe_diagnostic(message)}", file=sys.stderr)
            return 1
    if args.json:
        report = _report(command, result, written=written, path=request.profile_path)
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_text(command, result, written=written, path=request.profile_path)
    return 0


def install_main(argv: list[str] | None = None) -> int:
    """Entry point for ``install``.

    Args:
        argv: Command arguments.

    Returns:
        Exit status.
    """
    return run(Command.INSTALL, argv)


def update_main(argv: list[str] | None = None) -> int:
    """Entry point for ``update``.

    Args:
        argv: Command arguments.

    Returns:
        Exit status.
    """
    return run(Command.UPDATE, argv)
