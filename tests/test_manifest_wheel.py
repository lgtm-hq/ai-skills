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
from inventory_helpers import snapshot
from packaging.requirements import Requirement
from selection_helpers import collision_migration_case, edge_diagnostic_case
from test_selection_migrations import live_migration_case
from test_selection_roles import role_policy_case
from test_selection_skips import (
    SKIP_CONTROLS,
    check_rejected_collision_plan,
    rejected_collision_case,
)

from ai_skills_engine import cli
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.legacy import GENERATED_HEADER
from ai_skills_engine.manifest.load import read_document

pytest_plugins = ["inventory_helpers"]

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "control,expected",
    [("same-stem", 0), ("ordinary", 0), ("specialist-only", 1), ("unused", 1)],
)
def test_installed_skill_aliases_do_not_rename_specialists(
    installed_command: Path,
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    control: str,
    expected: int,
) -> None:
    """Real installed inventory and validation enforce the skill rename boundary."""
    from inventory_helpers import configure_inventory_aliases, inventory_snapshot

    root, vendor = inventory_repo
    configure_inventory_aliases(root=root, vendor=vendor, control=control)
    before = inventory_snapshot(root, vendor)
    operands = ["--repo-root", str(root), "--vendor-root", f"vendor={vendor}"]
    for command in (["inventory", "--json"], ["manifest", "validate"]):
        result = _run(
            args=[str(installed_command), *command, *operands],
            cwd=root.parent,
            expected=expected,
        )
        assert_that(cli.main([*command, *operands])).is_equal_to(expected)
        source = capsys.readouterr()
        assert_that((result.stdout, result.stderr)).is_equal_to(
            (source.out, source.err)
        )
        if expected:
            assert_that(result.stdout).contains(
                "inventory.invalid-payload",
                "Unused mapped capability/renameSkills",
                "reviewer" if control == "specialist-only" else "absent",
            )
        elif command[0] == "inventory":
            repeat = _run(
                args=[str(installed_command), *command, *operands], cwd=root.parent
            )
            assert_that(repeat.stdout).is_equal_to(result.stdout)
            capabilities = json.loads(result.stdout)["capabilities"]
            records = {item["id"]: item for item in capabilities}
            assert_that(
                records["vendor/tools:specialist/reviewer"]["aliases"]
            ).is_empty()
            assert_that(records["vendor/tools:skill/helper"]["aliases"]).is_equal_to(
                ["help-alias" if control == "same-stem" else "ordinary-helper"]
            )
            if control == "same-stem":
                assert_that(
                    records["vendor/tools:skill/reviewer"]["aliases"]
                ).is_equal_to(["review-helper"])
            for item in capabilities:
                if item["role"] != "skill":
                    assert_that(item["aliases"]).described_as(item["id"]).is_empty()
    assert_that(inventory_snapshot(root, vendor)).is_equal_to(before)


def test_installed_inventory_modes_survive_real_tarball_acquisition(
    installed_command: Path, inventory_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    """The installed public CLI agrees across permissions and actual extraction."""
    from inventory_helpers import inventory_snapshot, inventory_tarball

    root, vendor = inventory_repo
    targets = [
        vendor / "skills/help/danger.py",
        vendor / "agents/reviewer.md",
        vendor / "NOTICE.md",
        root / "shared/guide.md",
    ]
    control = vendor / "skills/help/control.py"
    control.write_bytes(targets[0].read_bytes())
    for tree in (root, vendor):
        for path in tree.rglob("*"):
            if path.is_file():
                path.chmod(0o664)
    control.chmod(0o775)
    before = inventory_snapshot(root, vendor)
    archive = tmp_path / "snapshot.tar.gz"
    archive.write_bytes(inventory_tarball(vendor))
    arguments = [
        str(installed_command),
        "inventory",
        "--repo-root",
        str(root),
        "--json",
    ]
    offline_arguments = [*arguments, "--vendor-root", f"vendor={vendor}"]
    offline = _run(args=offline_arguments, cwd=tmp_path).stdout
    python = _venv_executable(installed_command.parents[1], "python")
    fetched = _run(
        args=[
            str(python),
            "-I",
            "-c",
            """
import sys
from pathlib import Path
from unittest.mock import patch
from ai_skills_engine import cli
from ai_skills_engine.bake import vendor_plugins
from ai_skills_engine.inventory import payload
print(payload.__file__, file=sys.stderr)
with patch.object(
    vendor_plugins, '_http_get_bytes', return_value=Path(sys.argv[1]).read_bytes()
) as network:
    status = cli.main(sys.argv[2:])
    print(f'network_stub_calls={network.call_count}', file=sys.stderr)
raise SystemExit(status)
""",
            str(archive),
            *arguments[1:],
            "--fetch-vendors",
        ],
        cwd=tmp_path,
    )
    assert_that(fetched.stderr).contains(
        "site-packages/ai_skills_engine/inventory/payload.py", "network_stub_calls=1"
    ).does_not_contain(str(ROOT / "src"))
    baseline, acquired = json.loads(offline), json.loads(fetched.stdout)
    for section in ("capabilities", "resources"):
        assert_that(acquired[section]).is_equal_to(baseline[section])
    helper = next(
        item for item in acquired["capabilities"] if item["id"].endswith("/helper")
    )
    files = {item["path"]: item for item in helper["payload"]}
    assert_that(files["danger.py"]["mode"]).is_equal_to(0o644)
    assert_that(files["control.py"]["mode"]).is_equal_to(0o755)
    assert_that(files["danger.py"]["sha256"]).is_equal_to(files["control.py"]["sha256"])
    assert_that(inventory_snapshot(root, vendor)).is_equal_to(before)
    for path in targets:
        path.chmod(0o675)
    control.chmod(0o751)
    assert_that(_run(args=offline_arguments, cwd=tmp_path).stdout).is_equal_to(offline)
    identities = (
        "vendor/tools:skill/helper",
        "vendor/tools:specialist/reviewer",
        "vendor/tools:resource/notice",
        "fixture/tools:resource/guide",
    )
    for path, identity in zip(targets, identities, strict=True):
        section = "resources" if ":resource/" in identity else "capabilities"
        original = next(item for item in baseline[section] if item["id"] == identity)
        path.chmod(0o775)
        changed = json.loads(_run(args=offline_arguments, cwd=tmp_path).stdout)
        executable = next(item for item in changed[section] if item["id"] == identity)
        assert_that(executable["tree_digest"]).is_not_equal_to(original["tree_digest"])
        path.write_bytes(path.read_bytes() + b"\n# installed byte change\n")
        changed = json.loads(_run(args=offline_arguments, cwd=tmp_path).stdout)
        content = next(item for item in changed[section] if item["id"] == identity)
        assert_that(content["tree_digest"]).is_not_equal_to(executable["tree_digest"])
    assert_that(list(root.rglob("MUST-NOT-EXECUTE"))).is_empty()
    assert_that(list(vendor.rglob("MUST-NOT-EXECUTE"))).is_empty()


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
        shutil.copytree(src=ROOT / "skills/branch", dst=tmp_path / "skills/unknown")
    (tmp_path / "ai-skills.yaml").write_text(dump_document(data))
    before = {
        name: f"# installed sentinel {name}\n".encode()
        for name in ("bundles.yaml", "vendors.yaml")
    }
    for name, content in before.items():
        (tmp_path / name).write_bytes(content)
    args = [str(installed_command), "--repo-root", str(tmp_path)]
    _run(args=[*args, "manifest", "validate"], cwd=tmp_path)
    if change == "unknown-skill":
        # Recheck source loss after a successful real installed inventory check.
        shutil.rmtree(tmp_path / "skills/unknown")
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


def test_installed_plan_matches_source_and_refuses_selector_drift(
    installed_command: Path,
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An actual wheel plans an unrelated consumer, including closure and vetoes."""
    root, vendor = inventory_repo
    path = root / "ai-skills.yaml"
    document = read_document(path)
    document["packages"][0]["include"] = ["fixture/tools:skill/stable"]
    document["vendors"][0]["include"] = []
    path.write_text(dump_document(document))
    operands = ["--repo-root", str(root), "--vendor-root", f"vendor={vendor}"]
    lock = root / "ai-skills.lock"
    lock.write_bytes(b"existing lock\n")
    generation = root / "generation"
    generation.write_bytes(b"existing installation\n")
    for control, expected in (
        ("closure", 0),
        ("excluded-resource", 1),
        ("drift", 1),
        ("migration", 0),
    ):
        if control == "excluded-resource":
            document["vendors"][0]["exclude"] = ["vendor/tools:resource/notice"]
        elif control == "drift":
            document["vendors"][0].pop("exclude")
            document["packages"][0]["include"] = ["fixture/tools:skill/old-id"]
        elif control == "migration":
            document["overrides"] = {
                "migrations": [
                    {
                        "from": "fixture/tools:skill/old-id",
                        "to": "fixture/tools:skill/stable",
                    }
                ]
            }
        path.write_text(dump_document(document))
        before = {
            str(item.relative_to(root)): item.read_bytes()
            for item in root.rglob("*")
            if item.is_file()
        }
        for command in (["plan", "--json"], ["plan"]):
            installed = _run(
                args=[str(installed_command), *command, *operands],
                cwd=root.parent,
                expected=expected,
            )
            repeated = _run(
                args=[str(installed_command), *command, *operands],
                cwd=root.parent,
                expected=expected,
            )
            assert_that(repeated.stdout).is_equal_to(installed.stdout)
            assert_that(cli.main([*command, *operands])).is_equal_to(expected)
            source = capsys.readouterr()
            assert_that((installed.stdout, installed.stderr)).is_equal_to(
                (source.out, source.err)
            )
            if command[-1] == "--json":
                output = json.loads(installed.stdout)
                assert_that(output["capabilities"]).is_length(8)
                assert_that(output["resources"]).is_length(2)
                if expected:
                    assert_that(
                        [item["code"] for item in output["diagnostics"]]
                    ).contains(
                        "selection.required-excluded"
                        if control == "excluded-resource"
                        else "selection.selector-unmatched"
                    )
                else:
                    helper = next(
                        item
                        for item in output["capabilities"]
                        if item["id"] == "vendor/tools:skill/helper"
                    )
                    assert_that(helper["state"]).is_equal_to("pulled-in")
        after = {
            str(item.relative_to(root)): item.read_bytes()
            for item in root.rglob("*")
            if item.is_file()
        }
        assert_that(after).is_equal_to(before)
    assert_that(lock.read_bytes()).is_equal_to(b"existing lock\n")
    assert_that(generation.read_bytes()).is_equal_to(b"existing installation\n")


@pytest.mark.parametrize(
    ("control", "expected"),
    [
        ("exclude", 0),
        ("narrow", 0),
        ("kept", 1),
        ("required", 1),
        ("stale", 1),
        ("related", 0),
    ],
)
def test_installed_plan_rejected_payload_and_advisory_controls(
    installed_command: Path,
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    control: str,
    expected: int,
) -> None:
    """Installed public CLI preserves source behavior and both trees' bytes/modes."""
    root, vendor = inventory_repo
    document = read_document(root / "ai-skills.yaml")
    broken = vendor / "skills/broken"
    broken.mkdir()
    (broken / "SKILL.md").write_text("---\nname: broken\n---\nbody\n")
    identity = "vendor/tools:skill/broken"
    if control in {"exclude", "related"}:
        document["vendors"][0]["exclude"] = [identity]
    elif control in {"narrow", "required"}:
        document["vendors"][0]["include"] = ["vendor/tools:skill/helper"]
    elif control == "stale":
        document["vendors"][0]["exclude"] = ["vendor/tools:skill/absent"]
    if control == "required":
        document["packages"][0]["capabilities"][0]["requires"].append(identity)
    elif control == "related":
        document["packages"][0]["capabilities"][0]["related"] = [
            "fixture/tools:skill/absent"
        ]
    (root / "ai-skills.yaml").write_text(dump_document(document))
    (root / "ai-skills.lock").write_bytes(b"untouched lock\n")
    (root / "installed-generation").write_bytes(b"untouched generation\n")
    before = snapshot(root, vendor)
    args = [
        "plan",
        "--json",
        "--repo-root",
        str(root),
        "--vendor-root",
        f"vendor={vendor}",
    ]
    installed = _run(
        args=[str(installed_command), *args], cwd=root.parent, expected=expected
    )
    assert_that(cli.main(args)).is_equal_to(expected)
    source = capsys.readouterr()
    assert_that((source.out, source.err)).is_equal_to(
        (installed.stdout, installed.stderr)
    )
    codes = [item["code"] for item in json.loads(source.out)["diagnostics"]]
    assert_that("selection.selector-unmatched" in codes).is_equal_to(control == "stale")
    assert_that(snapshot(root, vendor)).is_equal_to(before)


def _compare_installed_plan(
    *,
    installed_command: Path,
    root: Path,
    vendor: Path,
    capsys: pytest.CaptureFixture[str],
    expected: int,
) -> None:
    """Check real wheel/source plan output and complete input bytes/modes.

    Args:
        installed_command: Wheel-installed console script.
        root: Consumer fixture root.
        vendor: Offline vendor snapshot.
        capsys: Source CLI output capture.
        expected: Required exit status.
    """
    before = snapshot(root, vendor)
    args = [
        "plan",
        "--json",
        "--repo-root",
        str(root),
        "--vendor-root",
        f"vendor={vendor}",
    ]
    installed = _run(
        args=[str(installed_command), *args], cwd=root.parent, expected=expected
    )
    assert_that(cli.main(args)).is_equal_to(expected)
    source_output = capsys.readouterr()
    assert_that((source_output.out, source_output.err)).is_equal_to(
        (installed.stdout, installed.stderr)
    )
    assert_that(snapshot(root, vendor)).is_equal_to(before)


@pytest.mark.parametrize("source", ["local", "mapped", "manifest"])
@pytest.mark.parametrize(
    "edge",
    [
        "requires-rejected",
        "requires-missing",
        "resources-rejected",
        "resources-missing",
        "nonimported",
    ],
)
@pytest.mark.parametrize(
    "control", ["excluded", "narrow", "kept", "required", "transitive", "stale"]
)
def test_installed_plan_edge_diagnostic_scope(
    installed_command: Path,
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    source: str,
    edge: str,
    control: str,
) -> None:
    """The installed CLI trims only unreachable edges and matches source bytes."""
    root, vendor = inventory_repo
    edge_diagnostic_case(
        root=root, vendor=vendor, source=source, edge=edge, control=control
    )
    expected = 0 if control in {"excluded", "narrow"} else 1
    _compare_installed_plan(
        installed_command=installed_command,
        root=root,
        vendor=vendor,
        capsys=capsys,
        expected=expected,
    )


@pytest.mark.parametrize("kind", ["capability", "package"])
@pytest.mark.parametrize("action", ["rename", "skip"])
@pytest.mark.parametrize(
    "control", ["migrated", "current", "stale", "malformed", "cycle", "duplicate"]
)
def test_installed_plan_collision_migrations(
    installed_command: Path,
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    kind: str,
    action: str,
    control: str,
) -> None:
    """Actual wheel decisions migrate and reject duplicates without changing inputs."""
    root, vendor = inventory_repo
    collision_migration_case(root=root, control=control, action=action, kind=kind)
    expected = 0 if control in {"migrated", "current"} else 1
    _compare_installed_plan(
        installed_command=installed_command,
        root=root,
        vendor=vendor,
        capsys=capsys,
        expected=expected,
    )


@pytest.mark.parametrize("role", ["integration", "lifecycle"])
@pytest.mark.parametrize("rejected", [False, True], ids=["valid", "rejected"])
@pytest.mark.parametrize("allowed", [False, True], ids=["disallowed", "allowed"])
@pytest.mark.parametrize(
    "control", ["default", "selected", "excluded", "narrow", "required", "transitive"]
)
def test_installed_plan_role_eligibility(
    installed_command: Path,
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    role: str,
    rejected: bool,
    allowed: bool,
    control: str,
) -> None:
    """Role vetoes and retained failure witnesses agree in actual installed plans."""
    root, vendor = inventory_repo
    _, expected, _ = role_policy_case(
        root=root, role=role, rejected=rejected, allowed=allowed, control=control
    )
    _compare_installed_plan(
        installed_command=installed_command,
        root=root,
        vendor=vendor,
        capsys=capsys,
        expected=expected,
    )


@pytest.mark.parametrize("author", ["vendor", "consumer"])
@pytest.mark.parametrize(
    "kind", ["capability", "package", "resource", "package-resource"]
)
@pytest.mark.parametrize("rejected", [False, True], ids=["live", "typed-rejected"])
@pytest.mark.parametrize("control", ["baseline", "exclude", "required", "absent"])
def test_installed_plan_live_migration_precedence(
    installed_command: Path,
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    author: str,
    kind: str,
    rejected: bool,
    control: str,
) -> None:
    """Actual installed CLI cannot move a veto or required witness to another ID."""
    root, vendor = inventory_repo
    target, replacement = live_migration_case(
        root=root,
        vendor=vendor,
        author=author,
        kind=kind,
        rejected=rejected,
        control=control,
    )
    expected = int(control == "required")
    _compare_installed_plan(
        installed_command=installed_command,
        root=root,
        vendor=vendor,
        capsys=capsys,
        expected=expected,
    )
    installed = _run(
        args=[
            str(installed_command),
            "plan",
            "--json",
            "--repo-root",
            str(root),
            "--vendor-root",
            f"vendor={vendor}",
        ],
        cwd=root.parent,
        expected=expected,
    )
    output = json.loads(installed.stdout)
    section = "resources" if "resource" in kind else "capabilities"
    entries = {item["id"]: item for item in output[section]}
    identity = replacement if control == "absent" else target
    assert_that(entries[identity]["state"]).is_equal_to(
        "pulled-in" if control == "absent" else "excluded"
    )
    if control == "required":
        finding = next(
            item
            for item in output["diagnostics"]
            if item["code"] == "selection.required-excluded"
        )
        assert_that(finding["chain"]).is_equal_to(
            ["fixture/tools:skill/stable", target]
        )


@pytest.mark.parametrize("author", ["vendor", "consumer"])
@pytest.mark.parametrize("kind", ["capability", "package"])
@pytest.mark.parametrize("action", ["rename", "skip"])
@pytest.mark.parametrize("rejected", [False, True], ids=["live", "typed-rejected"])
def test_installed_live_migration_collision_answers(
    installed_command: Path,
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    author: str,
    kind: str,
    action: str,
    rejected: bool,
) -> None:
    """The installed planner keeps persisted answers bound to the live source ID."""
    root, vendor = inventory_repo
    target, replacement = live_migration_case(
        root=root,
        vendor=vendor,
        author=author,
        kind=kind,
        control=action,
        rejected=rejected,
    )
    expected = int(rejected and action == "rename")
    _compare_installed_plan(
        installed_command=installed_command,
        root=root,
        vendor=vendor,
        capsys=capsys,
        expected=expected,
    )
    installed = _run(
        args=[
            str(installed_command),
            "plan",
            "--json",
            "--repo-root",
            str(root),
            "--vendor-root",
            f"vendor={vendor}",
        ],
        cwd=root.parent,
        expected=expected,
    )
    entries = {
        item["id"]: item for item in json.loads(installed.stdout)["capabilities"]
    }
    if action == "skip":
        assert_that(entries[target]["state"]).is_equal_to("excluded")
    elif not rejected:
        assert_that(entries[target]["names"]).is_equal_to(["consumer-name"])
    else:
        assert_that(entries[target]["names"]).is_empty()
    assert_that(entries[replacement]["state"]).is_equal_to("selected")
    assert_that(entries[replacement]["names"]).does_not_contain("consumer-name")


@pytest.mark.parametrize("source", ["local", "mapped", "manifest"])
@pytest.mark.parametrize("control", SKIP_CONTROLS)
def test_installed_plan_rejected_collision_decisions(
    installed_command: Path,
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    source: str,
    control: str,
) -> None:
    """Real installed wheel replays known skips and preserves strict inventory."""
    from inventory_helpers import inventory_snapshot

    root, vendor = inventory_repo
    target, expected = rejected_collision_case(
        root=root, vendor=vendor, source=source, control=control
    )
    before = inventory_snapshot(root, vendor)
    operands = ["--json", "--repo-root", str(root), "--vendor-root", f"vendor={vendor}"]
    if not control.startswith("live"):
        strict = _run(
            args=[str(installed_command), "inventory", *operands],
            cwd=root.parent,
            expected=1,
        )
        assert_that(
            [item["code"] for item in json.loads(strict.stdout)["diagnostics"]]
        ).contains(
            "inventory.unknown-requires"
            if control == "required" and source != "local"
            else "inventory.invalid-payload"
        )
    installed = _run(
        args=[str(installed_command), "plan", *operands],
        cwd=root.parent,
        expected=expected,
    )
    assert_that(cli.main(["plan", *operands])).is_equal_to(expected)
    captured = capsys.readouterr()
    assert_that((captured.out, captured.err)).is_equal_to(
        (installed.stdout, installed.stderr)
    )
    check_rejected_collision_plan(
        output=json.loads(installed.stdout),
        target=target,
        control=control,
    )
    assert_that(inventory_snapshot(root, vendor)).is_equal_to(before)


def test_installed_selection_import_identity(
    installed_command: Path, tmp_path: Path
) -> None:
    """Bind the selection modules to the installed wheel, outside the checkout."""
    probe = _run(
        args=[
            str(_venv_executable(installed_command.parent.parent, "python")),
            "-I",
            "-c",
            (
                "import json; from ai_skills_engine.selection import rules, namespace; "
                "print(json.dumps([rules.__file__, namespace.__file__]))"
            ),
        ],
        cwd=tmp_path,
    )
    for path in json.loads(probe.stdout):
        assert_that(
            Path(path).is_relative_to(installed_command.parent.parent)
        ).is_true()
        assert_that(Path(path).is_relative_to(ROOT)).is_false()
    print(probe.stdout)
