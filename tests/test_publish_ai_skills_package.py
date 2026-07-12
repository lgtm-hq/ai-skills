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


def _npm_stub(*, published: bool) -> str:
    """Return a stub ``npm`` script body.

    Args:
        published: Whether ``npm view`` should report the version as present.

    Returns:
        Shell script source for the stub.
    """
    view_exit = "0" if published else "1"
    view_echo = '  echo "0.5.4"\n' if published else ""
    publish_guard = (
        'echo "npm publish should not run" >&2\nexit 99\n'
        if published
        else (
            'if [[ "$1" == "publish" ]]; then\n'
            '  echo "publish dry-run ok"\n'
            '  printf \'%s\\n\' "$@" > "${HOME}/npm-args.txt"\n'
            "  exit 0\n"
            "fi\n"
            "exit 2\n"
        )
    )
    return (
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "pack" ]]; then\n'
        '  echo "pack dry-run ok"\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "$1" == "view" ]]; then\n'
        f"{view_echo}"
        f"  exit {view_exit}\n"
        "fi\n"
        f"{publish_guard}"
    )


def _run_publish_script(
    *,
    tmp_path: Path,
    version: str,
    published: bool,
) -> subprocess.CompletedProcess[str]:
    """Run the publish script against a stubbed npm.

    Args:
        tmp_path: Temporary repository root.
        version: Package version to write.
        published: Whether the stub reports the version as already published.

    Returns:
        Completed process result.
    """
    _prepare_package(
        package_dir=tmp_path / "npm" / "ai-skills",
        version=version,
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(path=bin_dir / "npm", body=_npm_stub(published=published))
    script_path = _install_script_copy(repo_root=tmp_path)
    (tmp_path / "home").mkdir(exist_ok=True)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
        "LIVE": "0",
        "NPM_DIST_TAG": "latest",
        "HOME": str(tmp_path / "home"),
    }
    return subprocess.run(  # noqa: S603 # nosec B603 - test-local script copy
        [str(script_path)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        check=False,
    )


def test_dry_run_exits_zero_when_version_already_published(
    tmp_path: Path,
) -> None:
    """Dry-run succeeds after pack validation when the version exists."""

    result = _run_publish_script(
        tmp_path=tmp_path,
        version="0.5.4",
        published=True,
    )

    assert_that(result.returncode).is_equal_to(0)
    assert_that(result.stdout).contains("pack dry-run ok")
    assert_that(result.stdout).contains("DRY-RUN mode")
    assert_that(result.stdout).contains("Already published")
    assert_that(result.stdout).contains("@lgtm-hq/ai-skills@0.5.4")


def test_dry_run_publishes_when_version_is_unpublished(tmp_path: Path) -> None:
    """Dry-run packs, then runs npm publish --dry-run when unpublished."""

    result = _run_publish_script(
        tmp_path=tmp_path,
        version="9.9.9",
        published=False,
    )

    assert_that(result.returncode).is_equal_to(0)
    assert_that(result.stdout).contains("pack dry-run ok")
    assert_that(result.stdout).contains("publish dry-run ok")
    args = (tmp_path / "home" / "npm-args.txt").read_text(encoding="utf-8")
    assert_that(args).contains("--dry-run")
