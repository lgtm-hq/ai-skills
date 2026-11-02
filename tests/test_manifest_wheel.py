"""Build and install the actual wheel, then exercise manifest commands offline."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess  # nosec B404 - bounded local build/CLI processes, no shell
import sys
from email import message_from_bytes
from importlib.metadata import distribution
from pathlib import Path
from zipfile import ZipFile

import pytest
from assertpy import assert_that
from packaging.requirements import Requirement

from ai_skills_engine import cli
from ai_skills_engine.manifest.legacy import GENERATED_HEADER

ROOT = Path(__file__).resolve().parents[1]


def _run(
    *, args: list[str], cwd: Path, expected: int = 0
) -> subprocess.CompletedProcess[str]:
    """Run a real command without source-path overrides or network resolution.

    Args:
        args: Explicit command arguments, without shell evaluation.
        cwd: Unrelated scratch directory.
        expected: Required command exit status.

    Returns:
        Captured command output after checking its status.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}
    }
    env.update(UV_OFFLINE="1", UV_PYTHON_DOWNLOADS="never", PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(  # nosec B603 - local trusted argv, no shell or network
        args=args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert_that(result.returncode).described_as(
        f"{args}\n{result.stdout}\n{result.stderr}"
    ).is_equal_to(expected)
    return result


def _copy_runtime_dependencies(*, requirements: list[str], site: Path) -> None:
    """Seed only the wheel's runtime closure from installed local distributions.

    This avoids registry/cache availability in unit tests. The engine itself is
    installed from its wheel by uv; no editable path or tooling is copied.

    Args:
        requirements: Requires-Dist entries from the built wheel's metadata.
        site: Fresh interpreter's site-packages directory.
    """
    pending = list(requirements)
    copied: set[str] = set()
    while pending:
        requirement = Requirement(pending.pop())
        name = requirement.name.lower()
        if name in copied or (
            requirement.marker and not requirement.marker.evaluate({"extra": ""})
        ):
            continue
        dependency = distribution(requirement.name)
        assert_that(requirement.specifier.contains(dependency.version)).is_true()
        copied.add(name)
        pending.extend(dependency.requires or [])
        base = Path(dependency.locate_file("")).resolve()
        for member in dependency.files or []:
            source = Path(dependency.locate_file(member)).resolve()
            if source.is_file() and source.is_relative_to(base):
                target = site / source.relative_to(base)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src=source, dst=target)


@pytest.fixture(scope="module")
def installed_command(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Install a fresh wheel outside the checkout and prove every package byte.

    Args:
        tmp_path_factory: Isolated build/install directories.

    Returns:
        The actual installed console-script executable.
    """
    root = tmp_path_factory.mktemp("manifest-wheel")
    assert_that(root.resolve().is_relative_to(ROOT)).is_false()
    assert_that(Path(cli.__file__).resolve()).is_equal_to(
        ROOT / "src/ai_skills_engine/cli.py"
    )
    _run(
        args=["uv", "build", "--offline", "--wheel", "--out-dir", str(root), str(ROOT)],
        cwd=root,
    )
    wheels = list(root.glob("*.whl"))
    assert_that(wheels).is_length(1)
    wheel = wheels[0]
    environment = root / "venv"
    _run(
        args=["uv", "venv", "--offline", "--python", sys.executable, str(environment)],
        cwd=root,
    )
    python = environment / "bin/python"
    _run(
        args=[
            "uv",
            "pip",
            "install",
            "--offline",
            "--no-deps",
            "--python",
            str(python),
            str(wheel),
        ],
        cwd=root,
    )
    probe = _run(
        args=[
            str(python),
            "-I",
            "-c",
            'import sysconfig; print(sysconfig.get_path("purelib"))',
        ],
        cwd=root,
    )
    site = Path(probe.stdout.strip())
    assert_that(site.is_relative_to(environment)).is_true()
    with ZipFile(wheel) as archive:
        metadata = message_from_bytes(
            archive.read(
                next(
                    name
                    for name in archive.namelist()
                    if name.endswith(".dist-info/METADATA")
                )
            )
        )
        _copy_runtime_dependencies(
            requirements=metadata.get_all("Requires-Dist", []), site=site
        )
        probe = _run(
            args=[
                str(python),
                "-I",
                "-c",
                (
                    "from ai_skills_engine.manifest import validate; "
                    "print(validate.__file__)"
                ),
            ],
            cwd=root,
        )
        assert_that(Path(probe.stdout.strip())).is_equal_to(
            site / "ai_skills_engine/manifest/validate.py"
        )
        members = [
            name
            for name in archive.namelist()
            if name.startswith("ai_skills_engine/") and not name.endswith("/")
        ]
        for name in members:
            assert_that((site / name).read_bytes()).described_as(name).is_equal_to(
                archive.read(name)
            )
            assert_that(archive.read(name)).described_as(name).is_equal_to(
                (ROOT / "src" / name).read_bytes()
            )
        schema = "ai_skills_engine/manifest/ai-skills.v1.schema.json"
        assert_that(members).contains(schema)
        assert_that(archive.read(schema)).is_equal_to(
            (ROOT / "schemas/ai-skills.v1.schema.json").read_bytes()
        )
    print(
        json.dumps(
            {
                "wheel": str(wheel),
                "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "bound_validator": probe.stdout.strip(),
                "matched_members": len(members),
            },
        )
    )
    return environment / "bin/ai-skills-engine"


@pytest.mark.parametrize(
    ("version", "expected"), [("ai-skills.dev/v1", 0), ("ai-skills.dev/v2", 1)]
)
def test_installed_manifest_validation_matches_source(
    installed_command: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    version: str,
    expected: int,
) -> None:
    """Valid/invalid minimal consumers need neither author checkout nor schema."""
    (tmp_path / "ai-skills.yaml").write_text(
        f"apiVersion: {version}\npublisher: {{id: consumer}}\n", encoding="utf-8"
    )
    args = ["manifest", "validate", "--repo-root", str(tmp_path)]
    result = _run(
        args=[str(installed_command), *args], cwd=tmp_path.parent, expected=expected
    )
    assert_that(cli.main(args)).is_equal_to(expected)
    source = capsys.readouterr()
    assert_that((result.stdout, result.stderr)).is_equal_to((source.out, source.err))
    if expected:
        assert_that(result.stdout).contains("schema", "/apiVersion")
    assert_that(list(tmp_path.iterdir())).is_equal_to([tmp_path / "ai-skills.yaml"])


def test_installed_migration_and_legacy_match_source(
    installed_command: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Real installed commands retain one-shot, drift, and exact-byte contracts."""
    repositories = [tmp_path / "installed", tmp_path / "source"]
    originals = {
        name: (ROOT / "tests/fixtures/manifest/legacy" / name).read_bytes()
        for name in ("bundles.yaml", "vendors.yaml")
    }
    for repository in repositories:
        repository.mkdir()
        for name, content in originals.items():
            (repository / name).write_bytes(content)
    for operation, expected in (
        (["migrate"], 0),
        (["validate"], 0),
        (["legacy", "--check"], 1),
        (["legacy"], 0),
        (["legacy", "--check"], 0),
        (["migrate"], 1),
    ):
        result = _run(
            args=[
                str(installed_command),
                "manifest",
                *operation,
                "--repo-root",
                str(repositories[0]),
            ],
            cwd=tmp_path,
            expected=expected,
        )
        assert_that(
            cli.main(["manifest", *operation, "--repo-root", str(repositories[1])])
        ).is_equal_to(expected)
        source = capsys.readouterr()
        assert_that((result.stdout, result.stderr)).is_equal_to(
            (source.out, source.err)
        )
    for name, content in originals.items():
        for repository in repositories:
            assert_that((repository / name).read_bytes()).is_equal_to(
                GENERATED_HEADER.encode() + content
            )
            assert_that((repository / name).read_bytes()).is_equal_to(
                (ROOT / name).read_bytes()
            )
