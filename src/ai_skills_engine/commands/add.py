"""``ai-skills-engine add``: import a pinned vendor, then ``lock``.

``add OWNER/REPO[@REF]`` resolves ``REF`` (default branch when omitted) to a
commit SHA, fetches that pin into the source cache and runs the ingest checks.
Nothing from the vendor is executed.

- A vendor with ``ai-skills.yaml`` gets a pinned ``vendors:`` entry whose
  ``include`` imports the upstream's explicit ``exports``.
- A vendor without one gets a consumer-owned ``mapping`` scaffold. Mapped
  identities are asserted by this repository, never by the upstream, so the
  scaffold is not locked until it is confirmed with ``--accept-mapping``.

Importing never re-exports: list a package under ``exports:`` to re-publish it.
"""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ai_skills_engine.commands.mapping_scaffold import (
    ACCEPT_HINT,
    SCAFFOLD_MARKER,
    kebab,
    mapping_scaffold,
)
from ai_skills_engine.lockfile import LOCK_FILENAME
from ai_skills_engine.manifest.edit import ManifestDumper, patch_document
from ai_skills_engine.manifest.identity import SEGMENT, matches, parse_id
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.transaction import restore_files, snapshot_files
from ai_skills_engine.manifest.validate import validate_document
from ai_skills_engine.registry.ingest_checks import safe_diagnostic, validate_input_tree
from ai_skills_engine.registry.ingest_limits import IngestLimits
from ai_skills_engine.registry.registry import load_unique_yaml_text
from ai_skills_engine.registry.vendor import Vendor
from ai_skills_engine.source_cache import SourceCache, materialize

_SPEC = re.compile(r"(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:@(?P<ref>[^\s@]+))?")
_SHA = re.compile(r"[0-9a-f]{40}")
FAILURES = (OSError, RuntimeError, TypeError, ValueError, KeyError)


def resolve_sha(*, repo: str, ref: str | None, branch: str | None) -> str:
    """Resolve a ref to a commit SHA through the shared repin resolver.

    Args:
        repo: ``owner/name``.
        ref: Tag, branch or commit; None tracks the default branch.
        branch: Explicit branch, taking precedence over ``ref``.

    Returns:
        40-hex commit SHA.
    """
    if ref is not None and _SHA.fullmatch(ref.lower()):
        return ref.lower()
    from ai_skills_engine.vendors.repin import resolve_upstream_sha

    return resolve_upstream_sha(
        vendor=Vendor(
            id="add",
            repo=repo,
            sha="0" * 40,
            skill_roots=(),
            license="",
            homepage="",
            display_ref=ref,
            branch=branch,
        )
    )


def fetch(*, alias: str, repo: str, sha: str, destination: Path) -> None:
    """Materialize the pin through the source cache and bound its tree.

    Args:
        alias: Consumer vendor alias.
        repo: ``owner/name``.
        sha: Pinned commit.
        destination: New directory for the extracted tree.
    """
    from ai_skills_engine.bake import vendor_plugins

    vendor = Vendor(
        id=alias, repo=repo, sha=sha, skill_roots=(), license="", homepage=""
    )
    materialize(
        cache=SourceCache.default(),
        vendor=vendor,
        dest=destination,
        # Resolved at call time so the shared bounded fetcher stays patchable.
        fetcher=lambda **kwargs: vendor_plugins._fetch_vendor_tree(**kwargs),
    )
    validate_input_tree(root=destination, vendor=alias, limits=IngestLimits())


def _qualified_exports(document: dict[str, Any]) -> list[str]:
    """Qualify an upstream manifest's explicit exports.

    Args:
        document: Upstream manifest.

    Returns:
        Exported package IDs in declaration order.
    """
    publisher = document["publisher"]["id"]
    return [
        value if "/" in value else f"{publisher}/{value}"
        for value in document.get("exports", [])
    ]


def _filters(
    *, include: Sequence[str], exclude: Sequence[str], available: Sequence[str]
) -> dict[str, list[str]]:
    """Validate user selectors against what the vendor actually offers.

    Args:
        include: ``--include`` selectors; empty imports everything offered.
        exclude: ``--exclude`` selectors.
        available: Exported or mapped package IDs.

    Returns:
        ``include``/``exclude`` manifest fields.

    Raises:
        ValueError: For malformed selectors or ones outside the offered packages.
    """
    for selector in (*include, *exclude):
        parse_id(selector, selector=True)
        if not any(
            matches(selector=selector, identity=package)
            or matches(selector=package, identity=selector)
            for package in available
        ):
            raise ValueError(
                f"{selector} is not offered by this vendor; available: "
                + ", ".join(available)
            )
    fields = {"include": list(include) or list(available)}
    return fields | ({"exclude": list(exclude)} if exclude else {})


def _upstream_entry(
    *, tree: Path, args: argparse.Namespace, base: dict[str, Any]
) -> dict[str, Any]:
    """Build the entry importing a manifest vendor's explicit exports.

    Args:
        tree: Fetched vendor tree containing ``ai-skills.yaml``.
        args: Parsed command line.
        base: Pin fields.

    Returns:
        Vendor declaration.

    Raises:
        ValueError: If the upstream manifest is invalid or exports nothing.
    """
    upstream = read_document(tree / "ai-skills.yaml")
    authority = {
        key: upstream.pop(key)
        for key in tuple(upstream)
        if key in {"policy", "overrides"} or key.startswith("x-")
    }
    # Like recursive loading, nested re-exports are verified against real pins
    # by ``lock``; every other upstream declaration error is fatal here.
    structural = [
        item
        for item in validate_document(upstream)
        if item.code != "dangling-export" or not upstream.get("vendors")
    ]
    if structural:
        raise ValueError(
            "invalid upstream ai-skills.yaml: "
            + "; ".join(f"{item.location}: {item.message}" for item in structural)
        )
    for key in sorted(authority):
        print(
            f"add: ignored upstream {key}: vendor policy, trust grants and "
            "overrides are never applied to this consumer"
        )
    exported = _qualified_exports(upstream)
    if not exported:
        raise ValueError("the upstream ai-skills.yaml exports nothing to import")
    return base | _filters(
        include=args.include, exclude=args.exclude, available=exported
    )


def _mapped_entry(
    *, tree: Path, args: argparse.Namespace, base: dict[str, Any]
) -> dict[str, Any]:
    """Build a consumer-owned mapping scaffold for a manifestless vendor.

    Args:
        tree: Fetched vendor tree without ``ai-skills.yaml``.
        args: Parsed command line.
        base: Pin fields.

    Returns:
        Vendor declaration, marked as a scaffold unless accepted.
    """
    mapping = mapping_scaffold(alias=base["id"], root=tree)
    packages = [f"{base['id']}/{package['id']}" for package in mapping["packages"]]
    entry = (
        base
        | {"mapping": mapping}
        | _filters(include=args.include, exclude=args.exclude, available=packages)
    )
    return entry if args.accept_mapping else entry | {SCAFFOLD_MARKER: True}


def append_vendor(*, text: str, data: dict[str, Any], entry: dict[str, Any]) -> str:
    """Append one vendor declaration, preserving the rest of the source.

    Args:
        text: Current manifest source.
        data: Parsed manifest.
        entry: New vendor declaration.

    Returns:
        Updated source with ambiguous SHA/branch values quoted.

    Raises:
        ValueError: If the edit would not preserve the requested values.
    """
    import yaml

    from ai_skills_engine.manifest.scalars import quote_vendor_scalars

    updated = {**data, "vendors": [*data.get("vendors", []), entry]}
    if "vendors" in data:
        return patch_document(text=text, data=updated)
    block = yaml.dump(
        {"vendors": [entry]},
        Dumper=ManifestDumper,
        sort_keys=False,
        width=80,
        allow_unicode=True,
    )
    result = quote_vendor_scalars(
        text=text + ("" if text.endswith("\n") else "\n") + block, data=updated
    )
    if load_unique_yaml_text(text=result) != updated:
        raise ValueError("Appending the vendor did not preserve the manifest")
    return result


def _lock(root: Path) -> int:
    """Run the public ``lock`` command for the edited manifest.

    Args:
        root: Consumer repository.

    Returns:
        ``lock`` exit status.
    """
    from ai_skills_engine.commands import lock as lock_command

    return lock_command.main(["--repo-root", str(root)])


def _accept(*, text: str, data: dict[str, Any], index: int) -> str:
    """Remove the scaffold marker from an existing mapped vendor.

    Args:
        text: Manifest source.
        data: Parsed manifest.
        index: Vendor position.

    Returns:
        Updated source.
    """
    vendors = [dict(item) for item in data["vendors"]]
    vendors[index].pop(SCAFFOLD_MARKER)
    return patch_document(text=text, data={**data, "vendors": vendors})


def _plan(*, root: Path, args: argparse.Namespace) -> tuple[str | None, bool]:
    """Compute the new manifest source.

    Args:
        root: Consumer repository.
        args: Parsed command line.

    Returns:
        New source, None for a no-op, and whether it may be locked.

    Raises:
        ValueError: For invalid input, alias conflicts or unusable vendors.
    """
    match = _SPEC.fullmatch(args.spec)
    if match is None:
        raise ValueError(f"expected OWNER/REPO[@REF], got {args.spec!r}")
    repo, ref = match["repo"], match["ref"]
    path = root / "ai-skills.yaml"
    if not path.is_file():
        raise ValueError("ai-skills.yaml not found; run `ai-skills-engine init`")
    text = path.read_text(encoding="utf-8")
    data = read_document(path)
    alias = args.id or kebab(repo.split("/", 1)[1])
    if not re.fullmatch(SEGMENT, alias):
        raise ValueError(f"vendor alias {alias!r} is not kebab-case; pass --id")
    for index, vendor in enumerate(data.get("vendors", [])):
        if vendor["id"] != alias and vendor["repo"].lower() != repo.lower():
            continue
        if vendor["id"] != alias or vendor["repo"].lower() != repo.lower():
            raise ValueError(
                f"vendor {vendor['id']} already imports {vendor['repo']}; "
                "choose another --id or edit the existing entry"
            )
        if vendor.get(SCAFFOLD_MARKER) is True:
            if not args.accept_mapping:
                raise ValueError(f"vendor {alias} mapping is pending; {ACCEPT_HINT}")
            print(f"add: accepted consumer-asserted mapping for vendor {alias}")
            return _accept(text=text, data=data, index=index), True
        print(
            f"add: vendor {alias} already pins {repo}@{vendor['sha']}; use "
            "`ai-skills-engine repin` to move it"
        )
        return None, False
    sha = resolve_sha(repo=repo, ref=ref, branch=args.branch)
    base: dict[str, Any] = {"id": alias, "repo": repo, "sha": sha}
    if args.branch is not None:
        base["branch"] = args.branch
    if ref is not None and not _SHA.fullmatch(ref.lower()):
        base["displayRef"] = ref
    for key in ("license", "homepage"):
        if getattr(args, key):
            base[key] = getattr(args, key)
    with TemporaryDirectory(prefix="ai-skills-add-") as temporary:
        tree = Path(temporary) / "tree"
        fetch(alias=alias, repo=repo, sha=sha, destination=tree)
        manifest = (tree / "ai-skills.yaml").is_file()
        entry = (
            _upstream_entry(tree=tree, args=args, base=base)
            if manifest
            else _mapped_entry(tree=tree, args=args, base=base)
        )
    print(f"add: {alias} -> {repo}@{sha}")
    if not manifest:
        print(
            "add: consumer-owned mapping; its identities are asserted by this "
            f"repository, not by {repo}"
        )
    return (
        append_vendor(text=text, data=data, entry=entry),
        SCAFFOLD_MARKER not in entry,
    )


def _parser() -> argparse.ArgumentParser:
    """Define the command line.

    Returns:
        Argument parser.
    """
    parser = argparse.ArgumentParser(prog="ai-skills-engine add", description=__doc__)
    parser.add_argument("spec", metavar="OWNER/REPO[@REF]")
    parser.add_argument("--repo-root", type=Path, help="Default: current directory")
    parser.add_argument("--id", help="Vendor alias (default: kebab-case repo name)")
    parser.add_argument("--branch", help="Upstream branch tracked for repins")
    parser.add_argument("--include", action="append", default=[], metavar="ID")
    parser.add_argument("--exclude", action="append", default=[], metavar="ID")
    parser.add_argument("--license", help="SPDX license recorded with the pin")
    parser.add_argument("--homepage", help="Homepage recorded with the pin")
    parser.add_argument(
        "--accept-mapping",
        action="store_true",
        help="Confirm a consumer-owned mapping for a vendor without a manifest",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Declare a pinned vendor import and lock it.

    Args:
        argv: Command arguments.

    Returns:
        Zero once locked; one on errors or an unaccepted mapping scaffold.
    """
    args = _parser().parse_args(argv)
    root = (args.repo_root or Path.cwd()).resolve()
    path = root / "ai-skills.yaml"
    try:
        updated, lockable = _plan(root=root, args=args)
    except FAILURES as error:
        print("add: " + safe_diagnostic(str(error)), file=sys.stderr)
        return 1
    if updated is None:
        return 0
    legacy = "x-legacy-format" in read_document(path)
    targets = [path, root / LOCK_FILENAME]
    if legacy:
        targets.extend((root / "vendors.yaml", root / "bundles.yaml"))
    originals = snapshot_files(targets)
    try:
        path.write_text(updated, encoding="utf-8")
        structural = [
            item
            for item in validate_document(read_document(path))
            if item.code == "schema"
        ]
        if structural:
            raise ValueError(
                "edited ai-skills.yaml is invalid: "
                + "; ".join(f"{item.location}: {item.message}" for item in structural)
            )
        if legacy:
            from ai_skills_engine.manifest.legacy import write_legacy

            write_legacy(root)
        if not lockable:
            print(
                f"add: wrote a mapping scaffold to {path.name}; not locked. "
                + ACCEPT_HINT[0].upper()
                + ACCEPT_HINT[1:]
            )
            return 1
        if _lock(root) != 0:
            raise RuntimeError("lock failed; ai-skills.yaml was restored")
    except FAILURES as error:
        restore_files(originals=originals, error=error)
        print("add: " + safe_diagnostic(str(error)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
