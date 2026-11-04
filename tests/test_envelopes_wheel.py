"""Run the built wheel's envelope commands outside the source checkout."""

import os
import shutil
import subprocess  # nosec B404 - trusted local wheel commands, no shell
import sys
from pathlib import Path

import yaml
from assertpy import assert_that

from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document

pytest_plugins = ["test_ingest_wheel"]

FIXTURE = Path(__file__).parent / "fixtures/envelopes"


def _tree(root: Path) -> dict[str, bytes]:
    """Read every regular file below a directory.

    Args:
        root: Directory to read.

    Returns:
        POSIX relative path to bytes.
    """
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_actual_wheel_generates_and_checks_envelopes(
    wheel_site: Path, tmp_path: Path
) -> None:
    """Shipped rules and the public entrypoint reproduce the goldens."""
    dependencies = Path(yaml.__file__).resolve().parent.parent
    launcher = tmp_path / "ai-skills-engine"
    launcher.write_text(
        f"#!{sys.executable} -I\n"
        "import sys\n"
        f"sys.path[:0] = {[str(wheel_site), str(dependencies)]!r}\n"
        "from importlib.metadata import Distribution\n"
        "distribution = Distribution.at(\n"
        f"    {str(next(wheel_site.glob('*.dist-info')))!r}\n)\n"
        "entry = next(item for item in distribution.entry_points\n"
        "    if item.group == 'console_scripts'\n"
        "    and item.name == 'ai-skills-engine')\n"
        "import ai_skills_engine.envelopes as envelopes\n"
        "from pathlib import Path\n"
        f"assert Path(envelopes.__file__).is_relative_to(Path({str(wheel_site)!r}))\n"
        "raise SystemExit(entry.load()())\n"
    )
    launcher.chmod(0o755)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {"PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONHOME"}
    }
    root = tmp_path / "author"
    shutil.copytree(src=FIXTURE / "source", dst=root)
    index = tmp_path / "index.json"
    shutil.copyfile(src=FIXTURE / "index.json", dst=index)
    assert_that(
        (wheel_site / "ai_skills_engine/data/envelope-rules.v1.json").read_bytes()
    ).is_equal_to((FIXTURE.parents[2] / "schemas/envelope-rules.v1.json").read_bytes())

    def run(*arguments: str) -> subprocess.CompletedProcess[str]:
        """Run the wheel entrypoint against the copied publication.

        Args:
            arguments: Command arguments after the repository root.

        Returns:
            Completed process.
        """
        return subprocess.run(
            args=[str(launcher), "--repo-root", str(root), *arguments],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )  # nosec B603 - explicit local wheel entrypoint, no shell

    built = run("generate", "--index", str(index), "--output", str(tmp_path / "b"))
    assert_that(built.returncode).described_as(built.stderr).is_zero()
    assert_that(_tree(tmp_path / "b")).is_equal_to(
        _tree(FIXTURE / "golden/built-unfiltered")
    )
    blocked = run("generate", "--check")
    assert_that(blocked.returncode).is_equal_to(1)
    assert_that(blocked.stderr).contains("package fixture/crew needs a built envelope")
    document = read_document(root / "ai-skills.yaml")
    document["exports"] = ["core", "extras"]
    (root / "ai-skills.yaml").write_text(dump_document(document))
    for arguments in (["generate"], ["generate", "--check"]):
        result = run(*arguments)
        assert_that(result.returncode).described_as(result.stderr).is_zero()
    assert_that(_tree(root / ".agents")).is_equal_to(
        {
            "plugins/marketplace.json": (
                FIXTURE / "golden/slice-unfiltered/.agents/plugins/marketplace.json"
            ).read_bytes()
        }
    )
    (root / ".agents/plugins/marketplace.json").write_text("{}\n")
    stale = run("generate", "--check")
    assert_that(stale.returncode).is_equal_to(1)
    assert_that(stale.stderr).contains(
        ".agents/plugins/marketplace.json is out of date"
    )
