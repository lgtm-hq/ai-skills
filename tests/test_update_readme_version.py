"""Tests for ``scripts/update-readme-version.sh``."""

from __future__ import annotations

import subprocess  # nosec B404 - tests only; run repo script via argv list without shell
from pathlib import Path

from assertpy import assert_that

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update-readme-version.sh"


def _run(
    *,
    args: list[str],
    env_version: str | None,
) -> subprocess.CompletedProcess[str]:
    """Run the update script with an optional NEXT_VERSION.

    Args:
        args: Positional arguments passed to the script.
        env_version: Value for NEXT_VERSION, or None to leave it unset.

    Returns:
        The completed subprocess result.
    """
    env = {"PATH": "/usr/bin:/bin"}
    if env_version is not None:
        env["NEXT_VERSION"] = env_version
    return subprocess.run(  # nosec B603 - fixed repo script path
        [str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        check=False,
    )


def test_help_flag_exits_zero() -> None:
    """--help prints usage and succeeds."""

    result = _run(args=["--help"], env_version=None)

    assert_that(result.returncode).is_equal_to(0)
    assert_that(result.stdout).contains("NEXT_VERSION")


def test_rewrites_all_pin_patterns(tmp_path: Path) -> None:
    """Git-tag, scoped npm, gh-release, and prose pins rewrite to NEXT_VERSION."""

    readme = tmp_path / "README.md"
    readme.write_text(
        "Matches the git release tag (`@0.1.10` ↔ `v0.1.10`):\n"
        "bunx skills add lgtm-hq/ai-skills@v0.1.10 -g\n"
        "bunx --package=@lgtm-hq/ai-skills@0.1.10 skill install …\n"
        "gh release download v0.1.10 -R lgtm-hq/ai-skills\n"
        "bunx skills add lgtm-hq/ai-skills@v0.1.10 -g --all\n",
        encoding="utf-8",
    )

    result = _run(args=[str(readme)], env_version="2.3.4")
    content = readme.read_text(encoding="utf-8")

    assert_that(result.returncode).is_equal_to(0)
    assert_that(content).contains("`@2.3.4` ↔ `v2.3.4`")
    assert_that(content).contains("lgtm-hq/ai-skills@v2.3.4 -g\n")
    assert_that(content).contains("@lgtm-hq/ai-skills@2.3.4 skill install")
    assert_that(content).contains("gh release download v2.3.4")
    assert_that(content).contains("lgtm-hq/ai-skills@v2.3.4 -g --all")
    assert_that(content).does_not_contain("0.1.10")
    assert_that(readme.with_suffix(".md.bak").exists()).is_false()


def test_rewrites_marketplace_plugin_versions(tmp_path: Path) -> None:
    """Marketplace stamps next to the README are rewritten with README pins."""

    readme = tmp_path / "README.md"
    readme.write_text(
        "bunx skills add lgtm-hq/ai-skills@v0.1.10 -g\n",
        encoding="utf-8",
    )
    marketplace = tmp_path / ".claude-plugin" / "marketplace.json"
    marketplace.parent.mkdir()
    marketplace.write_text(
        '{\n  "plugins": [\n    {\n      "name": "review",\n'
        '      "version": "0.1.10"\n    }\n  ]\n}\n',
        encoding="utf-8",
    )

    result = _run(args=[str(readme)], env_version="2.3.4")
    content = marketplace.read_text(encoding="utf-8")

    assert_that(result.returncode).is_equal_to(0)
    assert_that(result.stdout).contains("Pinned marketplace plugin versions to 2.3.4")
    assert_that(content).contains('"version": "2.3.4"')
    assert_that(content).does_not_contain("0.1.10")
    assert_that(marketplace.with_suffix(".json.bak").exists()).is_false()
    """The script fails fast when NEXT_VERSION is unset."""

    readme = tmp_path / "README.md"
    readme.write_text("x\n", encoding="utf-8")

    result = _run(args=[str(readme)], env_version=None)

    assert_that(result.returncode).is_not_equal_to(0)
    assert_that(result.stderr).contains("NEXT_VERSION is required")


def test_accepts_v_prefixed_next_version(tmp_path: Path) -> None:
    """A leading v on NEXT_VERSION is stripped, not rejected."""

    readme = tmp_path / "README.md"
    readme.write_text(
        "bunx skills add lgtm-hq/ai-skills@v0.1.10 -g\n",
        encoding="utf-8",
    )

    result = _run(args=[str(readme)], env_version="v2.3.4")

    assert_that(result.returncode).is_equal_to(0)
    assert_that(readme.read_text(encoding="utf-8")).contains(
        "lgtm-hq/ai-skills@v2.3.4",
    )


def test_rejects_malformed_next_version(tmp_path: Path) -> None:
    """A NEXT_VERSION that is not X.Y.Z is rejected."""

    readme = tmp_path / "README.md"
    readme.write_text("x\n", encoding="utf-8")

    result = _run(args=[str(readme)], env_version="1.2")

    assert_that(result.returncode).is_not_equal_to(0)
    assert_that(result.stderr).contains("must be X.Y.Z")


def test_rejects_missing_readme(tmp_path: Path) -> None:
    """A nonexistent README path is rejected."""

    result = _run(
        args=[str(tmp_path / "missing.md")],
        env_version="1.2.3",
    )

    assert_that(result.returncode).is_not_equal_to(0)
    assert_that(result.stderr).contains("README not found")
