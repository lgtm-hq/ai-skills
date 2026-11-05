"""Run the installed ``ai-skills-engine repin`` console script on local revisions.

Arguments: console script, repository root, revisions JSON
(``{"new": sha, "trees": {sha: {path: text}}}``), mode
(``updated``, ``failed`` or ``rollback``). Acquisition is replaced by a local
fake serving the JSON trees; any HTTP request fails. Prints a JSON report.
"""

import contextlib
import io
import json
import os
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

from ai_skills_engine import cli
from ai_skills_engine.bake import vendor_indexes, vendor_plugins
from ai_skills_engine.lockfile import read_lock
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.registry.vendor import Vendor
from ai_skills_engine.repin import run
from ai_skills_engine.vendors import manage


def main() -> None:
    """Prepare the locked fixture, run the console script, report observations."""
    command, directory, trees_path, mode = sys.argv[1:5]
    root = Path(directory)
    spec = json.loads(Path(trees_path).read_text())
    trees: dict[str, dict[str, str]] = spec["trees"]
    revision: str = spec["new"]
    os.environ["AI_SKILLS_CACHE"] = str(root.parent / "cache")

    def fetch(*, vendor: Vendor, dest: Path) -> None:
        """Write the pinned local tree instead of downloading it."""
        for relative, text in trees[vendor.sha].items():
            path = dest / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def paths(*, vendor: Vendor) -> list[str]:
        """List the pinned local tree for the index baker."""
        return sorted(trees[vendor.sha])

    def no_network(**kwargs: object) -> bytes:
        """Fail closed on any HTTP request."""
        raise AssertionError(f"unexpected network request: {kwargs.get('host')}")

    real_bake = vendor_indexes.bake

    def bake(*, repo_root: Path) -> None:
        """Keep the production baker; optionally fail after its writes."""
        real_bake(repo_root=repo_root)
        if mode == "rollback":
            raise RuntimeError("injected installed compatibility failure")

    def observe() -> dict[str, str]:
        """Record every file's bytes."""
        return {
            str(path.relative_to(root)): path.read_text(errors="replace")
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    with (
        patch.object(vendor_plugins, "_fetch_vendor_tree", fetch),
        patch.object(vendor_plugins, "_http_get_bytes", no_network),
        patch.object(vendor_indexes, "_fetch_tree_paths", paths),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        manage.refresh(repo_root=root)
        if cli.main(["--repo-root", str(root), "lock"]) != 0:
            raise AssertionError("fixture lock failed")
    before = observe()
    output, errors = io.StringIO(), io.StringIO()
    summary = root.parent / "body.md"
    argv = [
        command,
        "--repo-root",
        str(root),
        "repin",
        "--vendor",
        "example",
        "--revision",
        revision,
        "--json",
        "--summary-path",
        str(summary),
    ]
    status: object = None
    with (
        patch.object(vendor_plugins, "_fetch_vendor_tree", fetch),
        patch.object(vendor_plugins, "_http_get_bytes", no_network),
        patch.object(vendor_indexes, "_fetch_tree_paths", paths),
        patch.object(vendor_indexes, "bake", bake),
        patch.object(sys, "argv", argv),
        contextlib.redirect_stdout(output),
        contextlib.redirect_stderr(errors),
    ):
        try:
            runpy.run_path(command, run_name="__main__")
        except SystemExit as error:
            status = error.code
    after = observe()
    print(
        json.dumps(
            {
                "status": status,
                "report": json.loads(output.getvalue()),
                "stderr": errors.getvalue(),
                "summary": summary.read_text() if summary.exists() else None,
                "changed": sorted(
                    name
                    for name in before.keys() | after.keys()
                    if before.get(name) != after.get(name)
                ),
                "sha": read_document(root / "ai-skills.yaml")["vendors"][0]["sha"],
                "locked": [
                    item.sha for item in read_lock(root / "ai-skills.lock").vendors
                ],
                "module": run.__file__,
            }
        )
    )


if __name__ == "__main__":
    main()
