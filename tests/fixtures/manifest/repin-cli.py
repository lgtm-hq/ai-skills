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

from ai_skills_engine.bake import vendor_indexes, vendor_plugins
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.migrate import migrate
from ai_skills_engine.registry.vendor import Vendor
from ai_skills_engine.vendors import manage, repin

OLD_SHA = "0123456789abcdef0123456789abcdef01234567"
NEW_SHA = "89abcdef0123456789abcdef0123456789abcdef"
BASELINE_SHA = "fedcba9876543210fedcba9876543210fedcba98"


def main() -> None:
    """Run the actual console script, observing files independently of rollback."""
    command, directory, trees, mode, boundary, blocked, operation = sys.argv[1:]
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
        path.chmod(0o640)
    before = {
        path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in paths
    }
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
    baseline = (root / "vendors.yaml").read_text().replace(OLD_SHA, BASELINE_SHA)
    failure = ValueError("primary installed repin failure")
    cleaning = False
    events: list[str] = []
    real_write, real_chmod, real_unlink = Path.write_bytes, Path.chmod, Path.unlink
    real_bake, real_sync = vendor_indexes.bake, manage._sync_artifacts

    def fail() -> None:
        """Inject the primary error after actual pin edits and production writes."""
        nonlocal cleaning
        notice.write_bytes(b"partial notice")
        absent.write_bytes(b"new notice")
        for path in paths:
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
        "example-vendor",
        "--json",
    ]
    if mode == "keep":
        argv.append("--keep-sha")
    if mode == "baseline":
        argv.extend(["--baseline-ref", "base"])
    output = io.StringIO()
    with (
        patch.object(vendor_indexes, "_fetch_tree_paths", fetch_index),
        patch.object(vendor_plugins, "_fetch_vendor_tree", fetch_plugin),
        patch.object(vendor_plugins, "_http_get_bytes", no_network),
        patch.object(
            repin,
            "resolve_upstream_sha",
            lambda **kw: OLD_SHA if mode == "noop" else NEW_SHA,
        ),
        patch.object(repin, "_registry_text_at_ref", lambda **kw: baseline),
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
            runpy.run_path(command, run_name="__main__")
        except SystemExit as error:
            status = error.code
    artifacts_after = observe_artifacts()
    print(
        json.dumps(
            {
                "status": status,
                "output": output.getvalue(),
                "events": events,
                "notes": getattr(failure, "__notes__", []),
                "changed": [
                    str(path.relative_to(root))
                    for path in paths
                    if (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                    != before[path]
                ],
                "absent_exists": absent.exists(),
                "changed_artifacts": sorted(
                    name
                    for name in artifacts_before.keys() | artifacts_after.keys()
                    if artifacts_before.get(name) != artifacts_after.get(name)
                ),
                "sha": read_document(manifest)["vendors"][0]["sha"],
                "module": repin.__file__,
            }
        )
    )


if __name__ == "__main__":
    main()
