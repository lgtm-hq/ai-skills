"""Build the actual wheel and run its public command outside the source checkout."""

import json
import os
import subprocess  # nosec B404 - trusted local wheel commands, no shell
import sys
from importlib import metadata
from pathlib import Path

import yaml
from assertpy import assert_that

pytest_plugins = ["artifact_helpers", "test_ingest_wheel"]


def test_actual_wheel_public_artifact_commands(
    wheel_site: Path, artifact_repo: Path, tmp_path: Path
) -> None:
    """Wheel entrypoint, schemas and drift commands work with isolated imports."""
    dependencies = Path(yaml.__file__).resolve().parent.parent
    launcher = tmp_path / "ai-skills-engine"
    # Use the entrypoint declared by the actual built wheel, not a source shim.
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
        "raise SystemExit(entry.load()())\n"
    )
    launcher.chmod(0o755)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {"PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONHOME"}
    }
    args = [str(launcher), "--repo-root", str(artifact_repo)]
    for command in (
        ["build", "--write-digests"],
        ["build", "--check"],
        ["bake", "artifacts", "--check"],
        ["build", "--check-inputs"],
    ):
        result = subprocess.run(
            args=[*args, *command],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )  # nosec B603 - explicit local wheel entrypoint, no shell
        assert_that(result.returncode).described_as(
            result.stdout + result.stderr
        ).is_zero()
    index = json.loads((artifact_repo / "dist/artifacts/index.json").read_text())
    distribution = metadata.Distribution.at(next(wheel_site.glob("*.dist-info")))
    assert_that(index["engineVersion"]).is_equal_to(distribution.version)
    assert_that(index["packages"][0]["capabilities"]).is_length(2)
    proof = subprocess.run(
        args=[
            sys.executable,
            "-I",
            "-c",
            (
                "import sys\n"
                f"sys.path[:0] = {[str(wheel_site), str(dependencies)]!r}\n"
                "from ai_skills_engine.artifacts.format import schema\n"
                "from importlib.resources import files\n"
                "print(files('ai_skills_engine.data')\n"
                "      .joinpath('artifact-index.v1.schema.json'))\n"
                "print(schema()['properties']['artifactFormat']['const'])\n"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )  # nosec B603 - fixed isolated interpreter argv, no shell
    assert_that(proof.returncode).described_as(proof.stderr).is_zero()
    assert_that(proof.stdout).contains(str(wheel_site), "\n1\n")
    source = artifact_repo / "shared/data/input.txt"
    source.write_text(source.read_text() + "Changed outside checkout.\n")
    failed = subprocess.run(
        args=[*args, "build", "--check"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )  # nosec B603 - explicit local wheel entrypoint, no shell
    assert_that(failed.returncode).is_equal_to(1)
    assert_that(failed.stderr).contains("rebuilt artifact digests")
