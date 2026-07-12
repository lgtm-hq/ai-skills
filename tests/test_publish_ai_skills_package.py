"""Tests for ``scripts/ci/npm/publish_ai_skills_package.sh``."""

from __future__ import annotations

import os
import stat
import subprocess  # nosec B404 - tests only; run repo script via argv list without shell
from pathlib import Path

from assertpy import assert_that

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "ci"
    / "npm"
    / "publish_ai_skills_package.sh"
)


def _write_executable(*, path: Path, body: str) -> None:
    """Write a shell script and mark it executable.

    Args:
        path: Destination path.
        body: Script contents.
    """
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _prepare_package(*, package_dir: Path, version: str) -> None:
    """Create a minimal npm package.json for the publish script.

    Args:
        package_dir: Directory that will hold package.json.
        version: Package version string.
    """
    package_dir.mkdir(parents=True, exist_ok=True)
    package_dir.joinpath("package.json").write_text(
        f'{{"name":"@lgtm-hq/ai-skills","version":"{version}"}}\n',
        encoding="utf-8",
    )


def _install_script_copy(*, repo_root: Path) -> Path:
    """Copy the publish script into a fake repo so REPO_ROOT resolves there.

    Args:
        repo_root: Fake repository root.

    Returns:
        Path to the executable script copy.
    """
    script_dir = repo_root / "scripts" / "ci" / "npm"
    script_dir.mkdir(parents=True)
    script_path = script_dir / "publish_ai_skills_package.sh"
    script_path.write_text(_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR)
    return script_path


def test_dry_run_exits_zero_when_version_already_published(
    tmp_path: Path,
) -> None:
    """Dry-run succeeds with an explicit message when the version exists."""

    _prepare_package(
        package_dir=tmp_path / "npm" / "ai-skills",
        version="0.5.4",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        path=bin_dir / "npm",
        body=(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "view" ]]; then\n'
            '  echo "0.5.4"\n'
            "  exit 0\n"
            "fi\n"
            'echo "npm publish should not run" >&2\n'
            "exit 99\n"
        ),
    )
    script_path = _install_script_copy(repo_root=tmp_path)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
        "LIVE": "0",
        "NPM_DIST_TAG": "latest",
        "HOME": str(tmp_path / "home"),
    }

    result = subprocess.run(  # noqa: S603 # nosec B603 - test-local script copy
        [str(script_path)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert_that(result.returncode).is_equal_to(0)
    assert_that(result.stdout).contains("DRY-RUN mode")
    assert_that(result.stdout).contains("Already published")
    assert_that(result.stdout).contains("@lgtm-hq/ai-skills@0.5.4")


def test_dry_run_publishes_when_version_is_unpublished(tmp_path: Path) -> None:
    """Dry-run proceeds to npm publish --dry-run when the version is absent."""

    _prepare_package(
        package_dir=tmp_path / "npm" / "ai-skills",
        version="9.9.9",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        path=bin_dir / "npm",
        body=(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "view" ]]; then\n'
            "  exit 1\n"
            "fi\n"
            'if [[ "$1" == "publish" ]]; then\n'
            '  echo "publish dry-run ok"\n'
            '  printf \'%s\\n\' "$@" > "${HOME}/npm-args.txt"\n'
            "  exit 0\n"
            "fi\n"
            "exit 2\n"
        ),
    )
    script_path = _install_script_copy(repo_root=tmp_path)
    (tmp_path / "home").mkdir()
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
        "LIVE": "0",
        "NPM_DIST_TAG": "latest",
        "HOME": str(tmp_path / "home"),
    }

    result = subprocess.run(  # noqa: S603 # nosec B603 - test-local script copy
        [str(script_path)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert_that(result.returncode).is_equal_to(0)
    assert_that(result.stdout).contains("publish dry-run ok")
    args = (tmp_path / "home" / "npm-args.txt").read_text(encoding="utf-8")
    assert_that(args).contains("--dry-run")
