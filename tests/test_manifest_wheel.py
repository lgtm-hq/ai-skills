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

pytest_plugins = ["inventory_helpers"]

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
        assert_that(members).contains("ai_skills_engine/data/host_attributes.yaml")
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
        for name, content in originals.items():
            (repository / name).write_bytes(content)
        # Validation now observes payloads too. Keep every historical assertion
        # and supply minimal real payloads for the legacy declaration fixture.
        bundles = read_document(repository / "bundles.yaml")
        names = [
            *bundles["ungrouped"],
            *(name for group in bundles["groups"].values() for name in group["skills"]),
        ]
        for name in names:
            directory = repository / "skills" / name
            directory.mkdir(parents=True)
            (directory / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Wheel fixture.\n---\n"
            )
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


@pytest.mark.parametrize("key", ["disable-model-invocation", "vendor-permission"])
@pytest.mark.parametrize(
    "attribute,expected,normalized",
    [
        ("true", 0, True),
        ("2026-11-02", 0, {"$yaml": "date", "value": "2026-11-02"}),
        (
            "{1: first, '1': second, nested: [true, text]}",
            0,
            {
                "$yaml": "mapping",
                "items": [["1", "second"], ["nested", [True, "text"]], [1, "first"]],
            },
        ),
        ("!!binary aGVsbG8=", 1, None),
    ],
    ids=["bool", "date", "mixed-keys", "unsupported"],
)
def test_installed_inventory_and_resource_boundary_match_source(
    installed_command: Path,
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    key: str,
    attribute: str,
    expected: int,
    normalized: object,
) -> None:
    """An unrelated consumer gets identical installed/source records and failures."""
    root, vendor = inventory_repo
    skill = root / "skills/start/SKILL.md"
    skill.write_text(
        skill.read_text().replace(
            "disable-model-invocation: true", f"{key}: {attribute}"
        )
    )
    missing_root = _run(
        args=[str(installed_command), "inventory", "--json"],
        cwd=root.parent,
        expected=2,
    )
    assert_that(missing_root.stderr).contains("No ai-skills repository", "--repo-root")
    operands = ["--repo-root", str(root), "--vendor-root", f"vendor={vendor}"]
    for command in (["inventory", "--json"], ["manifest", "validate"]):
        first = _run(
            args=[str(installed_command), *command, *operands],
            cwd=root.parent,
            expected=expected,
        )
        second = _run(
            args=[str(installed_command), *command, *operands],
            cwd=root.parent,
            expected=expected,
        )
        assert_that(second.stdout).is_equal_to(first.stdout)
        assert_that(cli.main([*command, *operands])).is_equal_to(expected)
        source = capsys.readouterr()
        assert_that((first.stdout, first.stderr)).is_equal_to((source.out, source.err))
        if expected:
            assert_that(first.stdout).contains(
                "inventory.invalid-host-attribute", key, "bytes"
            )
        else:
            assert_that(first.stdout).contains(
                "inventory.host-specific-frontmatter",
                "codex=unverified" if command[0] == "manifest" else '"codex"',
            )
            if command[0] == "inventory":
                start = next(
                    item
                    for item in json.loads(first.stdout)["capabilities"]
                    if item["id"] == "fixture/tools:skill/stable"
                )
                retained = next(
                    item for item in start["host_attributes"] if item["key"] == key
                )
                assert_that(json.loads(retained["value_json"])).is_equal_to(normalized)
                if key == "vendor-permission":
                    assert_that(retained["semantics"]).is_equal_to("unknown")
                    assert_that(dict(retained["hosts"])).is_equal_to(
                        {
                            "claude-code": "unverified",
                            "codex": "unverified",
                            "cursor": "unverified",
                        }
                    )
                    assert_that(first.stdout).contains("inventory.unknown-frontmatter")
    path = root / "ai-skills.yaml"
    document = read_document(path)
    document["packages"][0]["capabilities"][0]["resources"] = []
    path.write_text(dump_document(document))
    for command in (["inventory", "--json"], ["manifest", "validate"]):
        result = _run(
            args=[str(installed_command), *command, *operands],
            cwd=root.parent,
            expected=1,
        )
        assert_that(cli.main([*command, *operands])).is_equal_to(1)
        source = capsys.readouterr()
        assert_that((result.stdout, result.stderr)).is_equal_to(
            (source.out, source.err)
        )
        assert_that(result.stdout).contains("inventory.undeclared-resource")


@pytest.mark.parametrize("control", ["missing", "drop", "changed"])
def test_installed_host_table_is_authoritative_without_checkout_fallback(
    installed_command: Path,
    inventory_repo: tuple[Path, Path],
    control: str,
) -> None:
    """Installed package data cannot fall back to author data."""
    root, vendor = inventory_repo
    python = _venv_executable(installed_command.parent.parent, "python")
    probe = _run(
        args=[
            str(python),
            "-I",
            "-c",
            (
                "from importlib.resources import files; "
                'print(files("ai_skills_engine.data").joinpath("host_attributes.yaml"))'
            ),
        ],
        cwd=root.parent,
    )
    table = Path(probe.stdout.strip())
    assert_that(table.is_relative_to(installed_command.parent.parent)).is_true()
    assert_that(table.is_relative_to(ROOT)).is_false()
    original = table.read_bytes()
    try:
        if control == "missing":
            table.unlink()
        else:
            table.write_text(
                original.decode().replace(
                    "codex: unverified",
                    f"codex: {'drop' if control == 'drop' else 'refuse'}",
                )
            )
        result = _run(
            args=[
                str(installed_command),
                "inventory",
                "--json",
                "--repo-root",
                str(root),
                "--vendor-root",
                f"vendor={vendor}",
            ],
            cwd=root.parent,
            expected=0 if control == "changed" else 1,
        )
        if control == "changed":
            document = json.loads(result.stdout)
            start = next(
                item
                for item in document["capabilities"]
                if item["id"] == "fixture/tools:skill/stable"
            )
            assert_that(
                dict(start["host_attributes"][0]["hosts"])["codex"]
            ).is_equal_to("refuse")
        else:
            assert_that(result.stdout).contains(
                "inventory.invalid-payload",
                "host_attributes.yaml" if control == "missing" else "drop is forbidden",
            )
    finally:
        table.write_bytes(original)


@pytest.mark.parametrize(
    ("platform", "scripts", "suffix"),
    [("linux", "bin", ""), ("darwin", "bin", ""), ("win32", "Scripts", ".exe")],
)
def test_wheel_fixture_selects_platform_executables(
    installed_command: Path,
    inventory_repo: tuple[Path, Path],
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
        elif "importlib.resources" in args[-1]:
            output = str(
                environments[0]
                / "site-packages/ai_skills_engine/data/host_attributes.yaml"
            )
        elif args[1:3] == ["inventory", "--json"]:
            output = "inventory.invalid-payload host_attributes.yaml"
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
    # The later host-data control also launches an interpreter. Exercise that
    # lookup for every platform rather than certifying only fixture setup.
    test_installed_host_table_is_authoritative_without_checkout_fallback(
        installed_command=command, inventory_repo=inventory_repo, control="missing"
    )
    probes = [args for args in calls if args[1:3] == ["-I", "-c"]]
    assert_that(probes).is_length(3)
    assert_that([args[0] for args in probes]).contains_only(str(python))
