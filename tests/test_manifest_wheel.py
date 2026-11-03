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
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from assertpy import assert_that
from packaging.requirements import Requirement

from ai_skills_engine import cli
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.legacy import GENERATED_HEADER
from ai_skills_engine.manifest.load import read_document

ROOT = Path(__file__).resolve().parents[1]


def _venv_executable(environment: Path, name: str) -> Path:
    """Locate a uv virtual environment executable on the current platform.

    Args:
        environment: Fresh virtual environment root.
        name: Executable basename without a platform suffix.

    Returns:
        Platform-specific interpreter or console-script path.
    """
    if sys.platform == "win32":
        return environment / "Scripts" / f"{name}.exe"
    return environment / "bin" / name


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
        base = Path(str(dependency.locate_file(""))).resolve()
        for member in dependency.files or []:
            source = Path(str(dependency.locate_file(member))).resolve()
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
    python = _venv_executable(environment, "python")
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
    return _venv_executable(environment, "ai-skills-engine")


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
        shutil.copytree(src=ROOT / "skills", dst=repository / "skills")
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


@pytest.mark.parametrize(
    "change",
    [
        "baseline",
        "id-key-mismatch",
        "duplicate-skill",
        "missing-skill",
        "unknown-skill",
    ],
)
def test_installed_publication_requires_marketplace_acceptance(
    installed_command: Path, tmp_path: Path, change: str
) -> None:
    """Installed validation stays broad while legacy publication enforces consumers."""
    shutil.copytree(src=ROOT / "skills", dst=tmp_path / "skills")
    shutil.copy2(src=ROOT / "pyproject.toml", dst=tmp_path / "pyproject.toml")
    data = read_document(ROOT / "ai-skills.yaml")
    if change == "id-key-mismatch":
        data["packages"][0]["id"] = "git-workflow"
        data["exports"][data["exports"].index("git-pr")] = "git-workflow"
    elif change == "duplicate-skill":
        data["packages"][1]["capabilities"].append(
            {"id": "branch", "path": "skills/branch"}
        )
    elif change == "missing-skill":
        data["packages"][0]["capabilities"].pop(0)
    elif change == "unknown-skill":
        data["packages"][0]["capabilities"].append(
            {"id": "unknown", "path": "skills/unknown"}
        )
    (tmp_path / "ai-skills.yaml").write_text(dump_document(data))
    before = {
        name: f"# installed sentinel {name}\n".encode()
        for name in ("bundles.yaml", "vendors.yaml")
    }
    for name, content in before.items():
        (tmp_path / name).write_bytes(content)
    args = [str(installed_command), "--repo-root", str(tmp_path)]
    _run(args=[*args, "manifest", "validate"], cwd=tmp_path)
    expected = 0 if change == "baseline" else 1
    for flags in ([], ["--check"]):
        result = _run(
            args=[*args, "manifest", "legacy", *flags], cwd=tmp_path, expected=expected
        )
        if expected:
            assert_that(result.stdout).contains("bundles.yaml reader")
            for name, content in before.items():
                assert_that((tmp_path / name).read_bytes()).is_equal_to(content)
    if not expected:
        _run(args=[*args, "generate", "marketplace"], cwd=tmp_path)
        _run(args=[*args, "generate", "marketplace", "--check"], cwd=tmp_path)
        for name in before:
            assert_that((tmp_path / name).read_bytes()).is_equal_to(
                (ROOT / name).read_bytes()
            )


@pytest.mark.parametrize(
    ("option", "diagnostic"),
    [("--sha", "schema"), ("--homepage", "Legacy publication")],
)
def test_installed_management_rejection_restores_exact_files(
    installed_command: Path, tmp_path: Path, option: str, diagnostic: str
) -> None:
    """The installed management CLI rolls back before any vendor acquisition."""
    shutil.copytree(src=ROOT / "skills", dst=tmp_path / "skills")
    before = {}
    for name in ("ai-skills.yaml", "bundles.yaml", "vendors.yaml"):
        path = tmp_path / name
        content = b"# original installed bytes\r\n" + (
            ROOT / name
        ).read_bytes().replace(b"\n", b"\r\n")
        path.write_bytes(content)
        path.chmod(0o640)
        before[name] = (content, path.stat().st_mode)
    vendor_id = read_document(tmp_path / "ai-skills.yaml")["vendors"][0]["id"]
    result = _run(
        args=[
            str(installed_command),
            "--repo-root",
            str(tmp_path),
            "vendors",
            "update",
            "--id",
            vendor_id,
            option,
            "invalid",
        ],
        cwd=tmp_path.parent,
        expected=1,
    )
    assert_that(result.stdout + result.stderr).contains(diagnostic)
    assert_that(
        {
            name: ((tmp_path / name).read_bytes(), (tmp_path / name).stat().st_mode)
            for name in before
        }
    ).is_equal_to(before)


@pytest.mark.parametrize(
    ("platform", "scripts", "suffix"),
    [("linux", "bin", ""), ("darwin", "bin", ""), ("win32", "Scripts", ".exe")],
)
def test_wheel_fixture_selects_platform_executables(
    installed_command: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    scripts: str,
    suffix: str,
) -> None:
    """Exercise the fixture's path boundary without executing foreign binaries."""
    module = sys.modules[__name__]
    wheel = next(installed_command.parents[2].glob("*.whl"))
    calls: list[list[str]] = []
    environments: list[Path] = []

    def simulate_uv(
        *, args: list[str], cwd: Path, expected: int = 0
    ) -> subprocess.CompletedProcess[str]:
        """Replay local wheel installation and probes at the subprocess boundary."""
        calls.append(args)
        output = ""
        if args[:2] == ["uv", "build"]:
            (cwd / wheel.name).write_bytes(wheel.read_bytes())
        elif args[:2] == ["uv", "venv"]:
            environments.append(Path(args[-1]))
        elif args[:3] == ["uv", "pip", "install"]:
            site = environments[0] / "site-packages"
            with ZipFile(args[-1]) as archive:
                for name in archive.namelist():
                    if not name.endswith("/"):
                        target = site / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.read(name))
        elif "sysconfig" in args[-1]:
            output = str(environments[0] / "site-packages")
        else:
            output = str(
                environments[0] / "site-packages/ai_skills_engine/manifest/validate.py"
            )
        return subprocess.CompletedProcess(args, expected, stdout=output, stderr="")

    monkeypatch.setattr(module, "_run", simulate_uv)
    monkeypatch.setattr(
        module, "sys", SimpleNamespace(platform=platform, executable=sys.executable)
    )
    command = module.installed_command.__wrapped__(tmp_path_factory)
    environment = environments[0]
    python = environment / scripts / f"python{suffix}"
    assert_that(command).is_equal_to(
        environment / scripts / f"ai-skills-engine{suffix}"
    )
    install = next(args for args in calls if args[:3] == ["uv", "pip", "install"])
    assert_that(install[install.index("--python") + 1]).is_equal_to(str(python))
    probes = [args for args in calls if args[1:3] == ["-I", "-c"]]
    assert_that(probes).is_length(2)
    assert_that([args[0] for args in probes]).contains_only(str(python))
