"""Author CLI for the common Python engine; install commands arrive separately."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from ai_skills_engine import package_sync, validate_skills
from ai_skills_engine.artifacts import cli as artifact_cli
from ai_skills_engine.bake import vendor_indexes, vendor_plugins
from ai_skills_engine.commands import build as build_command
from ai_skills_engine.commands import lock as lock_command
from ai_skills_engine.generate import agents_md, marketplace, readme, skills_manifest
from ai_skills_engine.inventory import cli as inventory_cli
from ai_skills_engine.manifest import cli as manifest_cli
from ai_skills_engine.selection import cli as selection_cli
from ai_skills_engine.vendors import manage, repin


def _envelope_arguments(tokens: list[str]) -> list[str] | None:
    """Route bare ``generate`` and ``generate --option`` to envelope generation.

    Named targets such as ``generate readme`` keep their existing routes.

    Args:
        tokens: Command-line arguments without the program name.

    Returns:
        Envelope command arguments, or None for every other command.
    """
    position, prefix = 0, []
    while position < len(tokens) and tokens[position].startswith("--repo-root"):
        width = 1 if "=" in tokens[position] else 2
        prefix.extend(tokens[position : position + width])
        position += width
    if position >= len(tokens) or tokens[position] != "generate":
        return None
    rest = tokens[position + 1 :]
    if rest and (not rest[0].startswith("--") or rest[0] == "--help"):
        return None
    if prefix and "=" in prefix[0]:
        prefix = ["--repo-root", prefix[0].split("=", 1)[1]]
    return [*rest, *prefix]


def main(argv: list[str] | None = None) -> int:
    """Route arguments to the same entry points used by compatibility scripts.

    Args:
        argv: CLI arguments, defaulting to process arguments.

    Returns:
        Selected command's exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", help="Repository root override")
    commands = parser.add_subparsers(dest="command", required=True)
    routes: dict[str, Callable[[list[str] | None], int]] = {
        "validate-skills": validate_skills.main,
        "vendors": manage.main,
        "repin": repin.main,
        "package-sync": package_sync.main,
        "inventory": inventory_cli.main,
        "plan": selection_cli.main,
        "lock": lock_command.main,
        "build": build_command.main,
    }
    for name, handler in routes.items():
        commands.add_parser(name, add_help=False).set_defaults(handler=handler)
    for name, targets in {
        "manifest": {
            "validate": manifest_cli.validate,
            "migrate": manifest_cli.migration,
            "legacy": manifest_cli.legacy,
        },
        "generate": {
            "marketplace": marketplace.main,
            "readme": readme.main,
            "agents-md": agents_md.main,
            "skills-manifest": skills_manifest.main,
        },
        "bake": {
            "artifacts": artifact_cli.main,
            "vendor-indexes": vendor_indexes.main,
            "vendor-plugins": vendor_plugins.main,
        },
    }.items():
        group = commands.add_parser(name)
        subcommands = group.add_subparsers(dest="target", required=True)
        for target, handler in targets.items():
            subcommands.add_parser(target, add_help=False).set_defaults(handler=handler)
    tokens = list(sys.argv[1:] if argv is None else argv)
    if (envelope_args := _envelope_arguments(tokens)) is not None:
        return marketplace.main(envelope_args)
    args, remaining = parser.parse_known_args(tokens)
    if args.repo_root is not None:
        remaining.extend(["--repo-root", args.repo_root])
    selected: Callable[[list[str] | None], int] = args.handler
    return selected(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
