"""Exercise unpacked wheel imports with isolated Python and no dependency install."""

import contextlib
import io
import json
import os
import subprocess  # nosec B404 - execution methods are patched to fail
import sys
from pathlib import Path
from unittest.mock import patch


def forbidden(*_args: object, **_kwargs: object) -> None:
    """Fail if the ingested vendor payload attempts to execute anything."""
    raise RuntimeError("vendor execution attempted")


def main() -> None:
    """Run actual wheel entrypoints, proving import origin and private output."""
    site, dependencies, author, vendor_root, operation = sys.argv[1:]
    sys.path.insert(0, dependencies)
    sys.path.insert(0, site)
    from ai_skills_engine import cli
    from ai_skills_engine.bake import vendor_plugins
    from ai_skills_engine.manifest.validate import schema_path
    from ai_skills_engine.registry.ingest_checks import safe_diagnostic
    from ai_skills_engine.registry.registry import load_registry

    module = Path(vendor_plugins.__file__).resolve()
    if not module.is_relative_to(Path(site)):
        raise RuntimeError("wheel import escaped its isolated package root")
    if operation == "extract":
        from ai_skills_engine.registry import safe_tree

        # Resolve the host rename runtime before denying execution; libc lookup
        # may run ldconfig. No archive bytes have been read at this point.
        safe_tree._libc()
    stdout, stderr = io.StringIO(), io.StringIO()
    status = 0
    with contextlib.ExitStack() as stack:
        for name in ("Popen", "run", "call", "check_call", "check_output"):
            stack.enter_context(patch.object(subprocess, name, forbidden))
        for name in dir(os):
            if name.startswith(("exec", "spawn", "posix_spawn")) or name in {
                "system",
                "popen",
            }:
                stack.enter_context(patch.object(os, name, forbidden))
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                if operation == "bake":
                    vendor = load_registry(registry_path=Path(author) / "vendors.yaml")[
                        0
                    ]
                    vendor_plugins.bake(
                        repo_root=Path(author),
                        vendor_trees={vendor.id: Path(vendor_root)},
                    )
                elif operation == "legacy":
                    status = cli.main(["manifest", "legacy", "--repo-root", author])
                elif operation == "extract":
                    vendor_plugins._extract_tarball(
                        payload=Path(vendor_root).read_bytes(),
                        dest=Path(author),
                        vendor_id="synthetic-vendor",
                    )
                else:
                    status = cli.main(
                        ["bake", "vendor-plugins", "--check", "--repo-root", author]
                    )
            except ValueError as error:
                print(safe_diagnostic(str(error)), file=sys.stderr)
                status = 1
    print(
        json.dumps(
            {
                "status": status,
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
                "module": str(module),
                "schema": str(schema_path()),
            }
        )
    )


if __name__ == "__main__":
    main()
