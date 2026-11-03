"""Inject only real destination I/O and refresh acquisition failures in a wheel CLI."""

import contextlib
import io
import json
import runpy
import stat
import sys
from pathlib import Path
from unittest.mock import patch

from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.vendors import manage


def main() -> None:
    """Run the installed console script and report independently observed states."""
    command, directory, boundary, blocked = sys.argv[1:]
    root = Path(directory)
    registry = root / "ai-skills.yaml"
    data = read_document(registry)
    if boundary != "refresh":
        data["packages"][0]["description"] = "Installed publication change"
        data["vendors"][0]["sha"] = "f" * 40
        registry.write_text(dump_document(data))
    artifact = root / "NOTICE.md"
    artifact.write_bytes(b"original artifact\r\n")
    paths = [
        root / name
        for name in ("ai-skills.yaml", "bundles.yaml", "vendors.yaml", "NOTICE.md")
    ]
    before = {
        path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in paths
    }
    real_write = Path.write_bytes
    cleaning = False
    events: list[str] = []

    def refresh(*, repo_root: Path) -> None:
        """Replace acquisition with a deterministic partial downstream failure."""
        nonlocal cleaning
        for path in paths:
            path.write_bytes(b"partial refresh")
            path.chmod(0o666)
        cleaning = True
        raise ValueError("primary installed refresh failure")

    def write(path: Path, content: bytes) -> int:
        """Fail at exact publication or cleanup destinations, leaving render real."""
        nonlocal cleaning
        if boundary != "refresh" and not cleaning and path == root / boundary:
            cleaning = True
            events.append(path.name)
            real_write(path, b"partial publication")
            path.chmod(0o666)
            raise PermissionError("primary installed publication failure")
        if cleaning and path == root / blocked:
            events.append(f"cleanup:{blocked}")
            raise PermissionError("installed cleanup write denied")
        return real_write(path, content)

    argv = [command, "--repo-root", str(root)]
    if boundary == "refresh":
        argv.extend(
            ["vendors", "update", "--id", data["vendors"][0]["id"], "--sha", "f" * 40]
        )
    else:
        argv.extend(["manifest", "legacy"])
    output = io.StringIO()
    with (
        patch.object(manage, "refresh", refresh),
        patch.object(Path, "write_bytes", write),
        patch.object(sys, "argv", argv),
        contextlib.redirect_stdout(output),
        contextlib.redirect_stderr(output),
    ):
        try:
            runpy.run_path(command, run_name="__main__")
        except SystemExit as error:
            status = error.code
    print(
        json.dumps(
            {
                "status": status,
                "output": output.getvalue(),
                "events": events,
                "changed": [
                    path.name
                    for path in paths
                    if (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                    != before[path]
                ],
                "module": manage.__file__,
            }
        )
    )


if __name__ == "__main__":
    main()
