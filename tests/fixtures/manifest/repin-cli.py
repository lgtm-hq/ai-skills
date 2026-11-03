"""Exercise the installed repin command with local acquisition and actual bakes."""

import contextlib
import io
import json
import runpy
import shutil
import stat
import sys
from pathlib import Path
from unittest.mock import patch

from ai_skills_engine import cli
from ai_skills_engine.bake import vendor_indexes, vendor_plugins
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.legacy import render_legacy
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.migrate import migrate
from ai_skills_engine.registry.registry import load_registry
from ai_skills_engine.registry.vendor import Vendor
from ai_skills_engine.registry.vendor_repin_diff import render_json
from ai_skills_engine.vendors import manage, repin

OLD_SHA = "0123456789abcdef0123456789abcdef01234567"
NEW_SHA = "89abcdef0123456789abcdef0123456789abcdef"
BASELINE_SHA = "fedcba9876543210fedcba9876543210fedcba98"


def main() -> None:
    """Run the actual console script, observing files independently of rollback."""
    command, directory, trees, mode, boundary, blocked, operation = sys.argv[1:8]
    state, entry = sys.argv[8:] or ("current", "installed-cli")
    root, tree_root = Path(directory), Path(trees)

    def tree(vendor: Vendor) -> Path:
        """Select the same before/after fixture trees as the source API tests."""
        return tree_root / ("after" if vendor.sha == NEW_SHA else "before")

    def fetch_index(*, vendor: Vendor) -> list[str]:
        """Replace only network acquisition of the vendor file listing."""
        return [str(path.relative_to(tree(vendor))) for path in tree(vendor).rglob("*")]

    def fetch_plugin(*, vendor: Vendor, dest: Path) -> None:
        """Copy inert local vendor inputs; production bakers produce all outputs."""
        shutil.copytree(src=tree(vendor), dst=dest, dirs_exist_ok=True)

    def no_network(**kwargs: object) -> bytes:
        """Fail closed if an acquisition fake misses a network path."""
        raise AssertionError(f"Unexpected network request: {kwargs.get('host')}")

    with (
        patch.object(vendor_indexes, "_fetch_tree_paths", fetch_index),
        patch.object(vendor_plugins, "_fetch_vendor_tree", fetch_plugin),
        patch.object(vendor_plugins, "_http_get_bytes", no_network),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        migrate(root)
        manage.refresh(repo_root=root)
    manifest = root / "ai-skills.yaml"
    baseline = (root / "vendors.yaml").read_text().replace(OLD_SHA, BASELINE_SHA)
    if state != "current":
        data = read_document(manifest)
        data["vendors"][0].update(repo="changed/repository", branch="release/changed")
        data["packages"][0]["description"] = "Changed package description"
        manifest.write_text(dump_document(data))
        registry = root / "vendors.yaml"
        registry.write_text(
            registry.read_text().replace("example-vendor", "stale-vendor")
        )
    if state == "absent":
        for name in ("vendors.yaml", "bundles.yaml"):
            (root / name).unlink()
    elif boundary in {"bundles.yaml", "vendors.yaml"}:
        for name in ("vendors.yaml", "bundles.yaml"):
            path = root / name
            path.write_bytes(b"# original publication bytes\r\n" + path.read_bytes())
    manifest.write_bytes(b"# installed source bytes\r\n" + manifest.read_bytes())
    notice = root / "NOTICE.md"
    notice.write_bytes(b"original installed notice\r\n")
    absent = root / "npm/ai-skills/NOTICE.md"
    absent.unlink()
    paths = [
        root / name
        for name in ("ai-skills.yaml", "vendors.yaml", "bundles.yaml", "NOTICE.md")
    ]
    for path in paths:
        if path.exists():
            path.chmod(0o640)

    def observe_files() -> dict[Path, tuple[bytes, int] | None]:
        """Record absence as well as exact bytes and permissions."""
        return {
            path: (
                (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                if path.exists()
                else None
            )
            for path in paths
        }

    before = observe_files()
    artifact_paths = manage._generated_artifact_paths(repo_root=root)

    def observe_artifacts() -> dict[str, tuple[bytes, int]]:
        """Observe every generated file independently of the rollback helpers."""
        return {
            str(path.relative_to(root)): (
                path.read_bytes(),
                stat.S_IMODE(path.stat().st_mode),
            )
            for destination in artifact_paths
            for path in (
                [destination] if destination.is_file() else destination.rglob("*")
            )
            if path.is_file()
        }

    artifacts_before = observe_artifacts()
    failure = (
        PermissionError("primary installed repin failure")
        if boundary in {"bundles.yaml", "vendors.yaml"}
        else (
            RuntimeError("primary installed repin failure")
            if boundary == "resolve"
            else ValueError("primary installed repin failure")
        )
    )
    cleaning = False
    events: list[str] = []
    resolved: list[tuple[str, str | None, str]] = []
    caught_primary = False
    real_write, real_chmod, real_unlink = Path.write_bytes, Path.chmod, Path.unlink
    real_bake, real_sync = vendor_indexes.bake, manage._sync_artifacts

    def fail() -> None:
        """Inject the primary error after actual pin edits and production writes."""
        nonlocal cleaning
        notice.write_bytes(b"partial notice")
        absent.write_bytes(b"new notice")
        for path in paths:
            if path.exists():
                path.chmod(0o666)
        cleaning = True
        raise failure

    def bake(*, repo_root: Path) -> None:
        """Retain the production index baker and fail only after its writes."""
        events.append("index")
        real_bake(repo_root=repo_root)
        if boundary == "index":
            fail()

    def sync(*, repo_root: Path, check_only: bool) -> None:
        """Retain real package sync, including all generated package outputs."""
        events.append("sync")
        real_sync(repo_root=repo_root, check_only=check_only)
        if boundary == "sync":
            fail()

    def deny(path: Path, action: str) -> None:
        """Fail only an actual selected restoration operation after the primary."""
        if cleaning and path == root / blocked and operation == action:
            events.append(f"cleanup:{blocked}:{action}")
            raise PermissionError(f"installed cleanup {action} denied")

    def write(path: Path, content: bytes) -> int:
        """Inject at a destination byte write without replacing rollback."""
        if boundary == path.name and path.parent == root and not cleaning:
            events.append(f"publication:{path.name}")
            real_write(path, b"partial publication")
            fail()
        deny(path, "write")
        return real_write(path, content)

    def chmod(path: Path, mode: int, *, follow_symlinks: bool = True) -> None:
        """Inject a destination mode error without granting additional access."""
        deny(path, "mode")
        real_chmod(path, mode, follow_symlinks=follow_symlinks)

    def unlink(path: Path, missing_ok: bool = False) -> None:
        """Inject a deletion error for an output absent from the snapshot."""
        deny(path, "unlink")
        real_unlink(path, missing_ok=missing_ok)

    argv = [
        command,
        "--repo-root",
        str(root),
        "repin",
        "--id",
        "unknown-vendor" if boundary == "unknown" else "example-vendor",
        "--json",
    ]
    if mode == "keep":
        argv.append("--keep-sha")
    if mode == "baseline" or boundary == "baseline-parse":
        argv.extend(["--baseline-ref", "base"])
    if boundary == "baseline":
        argv.append("--baseline-ref=-invalid")
    if mode in {"list", "all", "all-unchanged"}:
        argv = argv[:4] + (
            ["--list-json"] if mode == "list" else ["--all", "--keep-sha"]
        )
        if mode == "all-unchanged":
            argv.extend(["--baseline-ref", "base"])

    def resolve(*, vendor: Vendor) -> str:
        """Observe authoritative input and inject only the upstream failure."""
        nonlocal cleaning
        resolved.append((vendor.repo, vendor.branch, vendor.sha))
        if boundary == "resolve":
            cleaning = True
            raise failure
        return OLD_SHA if mode == "noop" else NEW_SHA

    def read_baseline(*, repo_root: Path, git_ref: str) -> str:
        """Retain real baseline validation for the invalid-ref failure control."""
        if boundary == "baseline":
            return real_baseline(repo_root=repo_root, git_ref=git_ref)
        if boundary == "baseline-parse":
            return "vendors: invalid\n"
        if mode == "all-unchanged":
            return render_legacy(repo_root)[repo_root / "vendors.yaml"].decode()
        return baseline

    real_baseline = repin._registry_text_at_ref
    output = io.StringIO()
    status: str | int | None = None
    with (
        patch.object(vendor_indexes, "_fetch_tree_paths", fetch_index),
        patch.object(vendor_plugins, "_fetch_vendor_tree", fetch_plugin),
        patch.object(vendor_plugins, "_http_get_bytes", no_network),
        patch.object(
            repin,
            "resolve_upstream_sha",
            resolve,
        ),
        patch.object(repin, "_registry_text_at_ref", read_baseline),
        patch.object(vendor_indexes, "bake", bake),
        patch.object(manage, "_sync_artifacts", sync),
        patch.object(Path, "write_bytes", write),
        patch.object(Path, "chmod", chmod),
        patch.object(Path, "unlink", unlink),
        patch.object(sys, "argv", argv),
        contextlib.redirect_stdout(output),
        contextlib.redirect_stderr(output),
    ):
        try:
            if entry == "api":
                diff = repin.repin_vendor(
                    repo_root=root,
                    vendor_id=(
                        "unknown-vendor" if boundary == "unknown" else "example-vendor"
                    ),
                    keep_sha=mode == "keep",
                    baseline_ref="-invalid" if boundary == "baseline" else None,
                    baseline_registry_text=(
                        "vendors: invalid\n"
                        if boundary == "baseline-parse"
                        else baseline if mode == "baseline" else None
                    ),
                )
                print(render_json(diff=diff, display_ref=None))
                status = 0
            elif entry == "source-cli":
                status = cli.main(argv[1:])
            else:
                runpy.run_path(command, run_name="__main__")
        except SystemExit as error:
            status = error.code
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            if entry != "api":
                raise
            caught_primary = error is failure
            print(error)
            for note in getattr(error, "__notes__", ()):
                print(note)
            status = 1
    artifacts_after = observe_artifacts()
    print(
        json.dumps(
            {
                "status": status,
                "output": output.getvalue(),
                "events": events,
                "notes": getattr(failure, "__notes__", []),
                "caught_primary": caught_primary,
                "resolved": resolved,
                "changed": [
                    str(path.relative_to(root))
                    for path in paths
                    if observe_files()[path] != before[path]
                ],
                "absent_exists": absent.exists(),
                "changed_artifacts": sorted(
                    name
                    for name in artifacts_before.keys() | artifacts_after.keys()
                    if artifacts_before.get(name) != artifacts_after.get(name)
                ),
                "sha": read_document(manifest)["vendors"][0]["sha"],
                "published": (
                    [
                        [vendor.id, vendor.repo, vendor.branch, vendor.sha]
                        for vendor in load_registry(registry_path=root / "vendors.yaml")
                    ]
                    if (root / "vendors.yaml").exists() and boundary == "none"
                    else []
                ),
                "module": repin.__file__,
            }
        )
    )


if __name__ == "__main__":
    main()
