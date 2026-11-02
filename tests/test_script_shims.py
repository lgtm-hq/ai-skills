"""Exercise real compatibility scripts and the engine CLI on offline repositories."""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 - local Python entry points with explicit argv
import sys
import venv
from importlib.util import find_spec
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import package_sync
from ai_skills_engine.bake import vendor_indexes, vendor_plugins
from ai_skills_engine.generate import agents_md, marketplace, readme, skills_manifest

REPO = Path(__file__).resolve().parents[1]
COMMANDS = [
    ("validate_skills.py", ["validate-skills"], ["skills"], None),
    (
        "generate_marketplace.py",
        ["generate", "marketplace"],
        ["--check"],
        ".claude-plugin/marketplace.json",
    ),
    ("generate_readme.py", ["generate", "readme"], ["--check"], "README.md"),
    ("generate_agents_md.py", ["generate", "agents-md"], [], None),
    (
        "generate_skills_manifest.py",
        ["generate", "skills-manifest"],
        ["--check", "manifest.json"],
        "manifest.json",
    ),
    ("bake_vendor_indexes.py", ["bake", "vendor-indexes"], ["--check"], "NOTICE.md"),
    (
        "bake_vendor_plugins.py",
        ["bake", "vendor-plugins"],
        ["--check"],
        "plugins-baked/BAKE.json",
    ),
    ("manage_vendors.py", ["vendors"], ["check"], "NOTICE.md"),
    ("repin_vendor.py", ["repin"], ["--list-json"], None),
    (
        "ci/npm/sync_ai_skills_package.py",
        ["package-sync"],
        ["--check"],
        "npm/ai-skills/data/vendors.json",
    ),
]


@pytest.fixture(scope="session")
def checkout_python(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create an offline interpreter with runtime dependencies but no engine.

    Args:
        tmp_path_factory: Session-scoped scratch directories.

    Returns:
        Interpreter independent of installed/editable engine packages.
    """
    root = tmp_path_factory.mktemp("checkout-python")
    venv.EnvBuilder(with_pip=False).create(root)
    site = (
        root
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    for name in (
        "yaml",
        "markdown_it",
        "mdurl",
        "jsonschema",
        "jsonschema_specifications",
        "referencing",
        "rpds",
        "attr",
        "attrs",
    ):
        spec = find_spec(name)
        if spec is None or spec.origin is None:
            raise RuntimeError(f"Missing runtime dependency: {name}")
        shutil.copytree(Path(spec.origin).parent, site / name)
    return root / "bin" / "python3"


def checkout_env(python: Path) -> dict[str, str]:
    """Remove source/install overrides from a direct-invocation environment.

    Args:
        python: Clean interpreter whose bin directory supplies the shebang.

    Returns:
        Environment with no inherited Python package search overrides.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME"}
    }
    env["PATH"] = f"{python.parent}{os.pathsep}{env['PATH']}"
    return env


@pytest.fixture
def engine_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Generate a one-skill repository without fetching any vendor source.

    Args:
        tmp_path: Isolated fixture directory.
        monkeypatch: Replace the vendor tree fetch with fixed offline paths.

    Returns:
        Root of the generated repository.
    """
    files = {
        "pyproject.toml": '[project]\nname = "fixture"\nversion = "1.2.3"\n',
        "skills/example/SKILL.md": (
            "---\nname: example\ndescription: Fixture skill.\n---\n# Example\n"
        ),
        "bundles.yaml": "groups: {}\nungrouped: [example]\n",
        "vendors.yaml": (
            "vendors:\n  - id: fixture\n    repo: example/fixture\n"
            f"    sha: '{'a' * 40}'\n    skillRoots: [skills]\n"
            "    license: MIT\n    homepage: https://github.com/example/fixture\n"
        ),
        "README.md": "<!-- plugins:start -->\n<!-- plugins:end -->\n",
        "AGENTS.md": "# Fixture\n\n## Skills\n\nTotal skills: 0\n\n",
        "npm/ai-skills/package.json": '{"name": "fixture", "version": "0.0.0-dev"}\n',
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    root_args = ["--repo-root", str(tmp_path)]
    marketplace.main(root_args)
    readme.main(root_args)
    agents_md.main(root_args)
    skills_manifest.main([*root_args, "--output", str(tmp_path / "manifest.json")])
    monkeypatch.setattr(
        vendor_indexes,
        "_fetch_tree_paths",
        lambda *, vendor: ["skills/vendor-skill/SKILL.md"],
    )
    vendor_indexes.bake(repo_root=tmp_path)
    vendor_plugins.bake(repo_root=tmp_path)
    package_sync.main(root_args)
    return tmp_path


def run_engine(*, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run an actual Python process using this checkout's installed engine.

    Args:
        args: Python arguments selecting a script or the module CLI.
        cwd: Working directory for discovery and relative arguments.

    Returns:
        Captured output and exit status.
    """
    return subprocess.run(  # nosec B603 - trusted local Python argv, no shell
        args=[sys.executable, *args],
        cwd=cwd,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize(("script", "command", "flags", "stale_path"), COMMANDS)
@pytest.mark.parametrize("stale", [False, True], ids=["current", "drift"])
def test_shim_cli_parity(
    engine_repo: Path,
    script: str,
    command: list[str],
    flags: list[str],
    stale_path: str | None,
    stale: bool,
) -> None:
    """Scripts and CLI preserve stdout, stderr, status and drift failures."""
    if stale and stale_path is not None:
        path = engine_repo / stale_path
        content = path.read_text(encoding="utf-8")
        path.write_text(
            (
                content.replace("| Plugin |", "| Outdated |")
                if stale_path == "README.md"
                else "stale\n"
            ),
            encoding="utf-8",
        )
    shim = run_engine(args=[str(REPO / "scripts" / script), *flags], cwd=engine_repo)
    cli = run_engine(
        args=["-m", "ai_skills_engine.cli", *command, *flags], cwd=engine_repo
    )
    expected = int(stale and stale_path is not None)
    assert_that(shim.returncode).described_as(shim.stderr).is_equal_to(expected)
    assert_that((cli.returncode, cli.stdout, cli.stderr)).is_equal_to(
        (shim.returncode, shim.stdout, shim.stderr),
    )


@pytest.mark.parametrize(("script", "command", "flags", "stale_path"), COMMANDS)
def test_shim_cli_explicit_root(
    engine_repo: Path,
    tmp_path: Path,
    script: str,
    command: list[str],
    flags: list[str],
    stale_path: str | None,
) -> None:
    """Every command accepts an explicit root from an unrelated directory."""
    del stale_path
    outside = tmp_path.with_name(f"{tmp_path.name}-outside")
    outside.mkdir()
    # Commands with cwd-relative file operands retain those original semantics.
    flags = [
        str(engine_repo / flag) if flag in {"skills", "manifest.json"} else flag
        for flag in flags
    ]
    flags = [*flags, "--repo-root", str(engine_repo)]
    shim = run_engine(args=[str(REPO / "scripts" / script), *flags], cwd=outside)
    cli = run_engine(args=["-m", "ai_skills_engine.cli", *command, *flags], cwd=outside)
    assert_that(shim.returncode).described_as(shim.stderr).is_zero()
    assert_that((cli.returncode, cli.stdout, cli.stderr)).is_equal_to(
        (shim.returncode, shim.stdout, shim.stderr),
    )


@pytest.mark.parametrize(("script", "command", "flags", "stale_path"), COMMANDS)
def test_executable_shim_parity(
    engine_repo: Path,
    script: str,
    command: list[str],
    flags: list[str],
    stale_path: str | None,
) -> None:
    """Direct executable scripts preserve the original shebang-based invocation."""
    del stale_path
    env = dict(os.environ)
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env['PATH']}"
    shim = subprocess.run(  # nosec B603 - fixed local compatibility script argv
        args=[str(REPO / "scripts" / script), *flags],
        cwd=engine_repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    cli = run_engine(
        args=["-m", "ai_skills_engine.cli", *command, *flags], cwd=engine_repo
    )
    assert_that(shim.returncode).described_as(shim.stderr).is_zero()
    assert_that((cli.returncode, cli.stdout, cli.stderr)).is_equal_to(
        (shim.returncode, shim.stdout, shim.stderr),
    )


@pytest.mark.parametrize(("script", "command", "flags", "stale_path"), COMMANDS)
@pytest.mark.parametrize("executable", [False, True], ids=["python3", "executable"])
def test_fresh_checkout_shims(
    engine_repo: Path,
    checkout_python: Path,
    script: str,
    command: list[str],
    flags: list[str],
    stale_path: str | None,
    executable: bool,
) -> None:
    """All ten shims work without an installed engine or inherited PYTHONPATH."""
    del stale_path
    checkout = engine_repo / "checkout"
    for directory in ("scripts", "src"):
        shutil.copytree(REPO / directory, checkout / directory)
    env = checkout_env(checkout_python)
    probe = subprocess.run(  # nosec B603 - fixed local interpreter probe
        args=[
            str(checkout_python),
            "-c",
            "import importlib.util as u; print(u.find_spec('ai_skills_engine'))",
        ],
        cwd=engine_repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert_that((probe.returncode, probe.stdout)).is_equal_to((0, "None\n"))
    args = [str(checkout / "scripts" / script), *flags]
    if not executable:
        args.insert(0, str(checkout_python))
    shim = subprocess.run(  # nosec B603 - trusted copied checkout script argv
        args=args,
        cwd=engine_repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    cli = run_engine(
        args=["-m", "ai_skills_engine.cli", *command, *flags], cwd=engine_repo
    )
    assert_that(shim.returncode).described_as(shim.stderr).is_zero()
    assert_that((shim.returncode, shim.stdout, shim.stderr)).is_equal_to(
        (cli.returncode, cli.stdout, cli.stderr),
    )


def test_stdlib_manifest_checkout(engine_repo: Path) -> None:
    """Manifest direct execution needs neither installed engine nor dependencies."""
    env = checkout_env(Path(sys.executable))
    result = subprocess.run(  # nosec B603 - fixed local stdlib-only script invocation
        args=[
            sys.executable,
            "-S",
            str(REPO / "scripts/generate_skills_manifest.py"),
            "--check",
            "manifest.json",
        ],
        cwd=engine_repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert_that(result.returncode).described_as(result.stderr).is_zero()
