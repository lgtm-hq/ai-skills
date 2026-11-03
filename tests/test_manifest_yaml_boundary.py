"""Keep the permissive production parser distinct from strict manifest publication."""

import json
import os
import subprocess  # nosec B404 - fixed offline parser fixture, no shell
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.manifest.legacy import render_legacy, write_legacy
from ai_skills_engine.manifest.load import load_manifest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def renovate_yaml_module() -> Path:
    """Resolve the locked parser read-only, including isolated dependency setups.

    Returns:
        Installed YAML parser entry with its exact development dependency version.
    """
    package = ROOT / "npm/ai-skills"
    prepared = Path(
        os.environ.get("RENOVATE_TEST_NODE_MODULES", package / "node_modules")
    )
    directory = prepared / "yaml"
    metadata = json.loads((directory / "package.json").read_text())
    expected = json.loads((package / "package.json").read_text())["devDependencies"][
        "yaml"
    ]
    assert_that(metadata["version"]).is_equal_to(expected)
    return (directory / metadata["main"]).resolve()


@pytest.mark.parametrize("line_ending", ["\n", "\r\n", ""])
def test_unseparated_comment_production_parser_differential(
    tmp_path: Path,
    renovate_yaml_module: Path,
    line_ending: str,
) -> None:
    """Production accepts the literal; the real publication path rejects it."""
    source = (ROOT / "ai-skills.yaml").read_text()
    if line_ending:
        source = source.replace(
            "branch: main\n",
            'branch: "main"#no-separation' + line_ending,
            1,
        )
    else:
        source = (
            "apiVersion: ai-skills.dev/v1\npublisher: {id: example}\n"
            "exports: []\nvendors:\n  - id: first\n"
            '    repo: owner/first\n    sha: "'
            + "a" * 40
            + '"\n    branch: "main"#no-separation'
        )
    result = (
        subprocess.run(  # nosec B603 B607 - fixed parser, no shell/network/vendor code
            [
                "bun",
                str(ROOT / "tests/fixtures/manifest/renovate-parse.mjs"),
                str(renovate_yaml_module),
            ],
            input=source,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    )
    assert_that(result.returncode).described_as(result.stderr).is_zero()
    parsed = json.loads(result.stdout)
    assert_that(parsed["errors"]).is_empty()
    assert_that(parsed["parsed"][0]["vendors"][0]["branch"]).is_equal_to("main")
    path = tmp_path / "ai-skills.yaml"
    path.write_text(source)
    sentinels = {
        tmp_path / name: f"sentinel {name}\n".encode()
        for name in ("bundles.yaml", "vendors.yaml")
    }
    for destination, raw in sentinels.items():
        destination.write_bytes(raw)
    for operation in (
        lambda: load_manifest(path),
        lambda: render_legacy(tmp_path),
        lambda: write_legacy(tmp_path),
        lambda: write_legacy(tmp_path, check=True),
    ):
        with pytest.raises(
            ValueError, match="comments after quoted scalars require whitespace"
        ):
            operation()
    args = ["--repo-root", str(tmp_path), "manifest"]
    for command in (["validate"], ["legacy"], ["legacy", "--check"]):
        assert_that(cli.main([*args, *command])).is_equal_to(1)
    for destination, raw in sentinels.items():
        assert_that(destination.read_bytes()).is_equal_to(raw)


@pytest.mark.parametrize(
    "suffix",
    [
        'x-comment: "main" # separated\n',
        "x-comment: 'branch: \"main\"#no-separation'\n",
        'x-comment: |-\n  branch: "main"#no-separation\n',
    ],
)
def test_quoted_content_and_separated_comments_remain_valid(
    tmp_path: Path, suffix: str
) -> None:
    """Quoted or block scalar content is not confused with an external comment."""
    path = tmp_path / "ai-skills.yaml"
    source = (ROOT / "ai-skills.yaml").read_text() + suffix
    path.write_text(source)
    load_manifest(path)
    assert_that(write_legacy(tmp_path)).is_zero()
    assert_that(write_legacy(tmp_path, check=True)).is_zero()
