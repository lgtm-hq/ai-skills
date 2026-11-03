"""Mandatory real Renovate parser differential for the prepared gateway gate.

Intentionally outside tests/: the Python reusable job has no Bun or node modules.
Missing runtime prerequisites are errors here, never skips or downloads.
"""

import json
import os
import subprocess  # nosec B404 - fixed offline parser fixture, no shell
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine.manifest.load import read_document

ROOT = Path(__file__).resolve().parents[3]


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
    entry = metadata["main"]
    if not isinstance(entry, str):
        raise TypeError("Locked YAML parser entry must be a string")
    return (directory / entry).resolve()


@pytest.mark.parametrize("line_ending", ["\n", "\r\n", ""])
@pytest.mark.parametrize("separated", [False, True])
def test_production_parser_differential(
    tmp_path: Path,
    renovate_yaml_module: Path,
    line_ending: str,
    separated: bool,
) -> None:
    """Production strict:false accepts both; publication enforces YAML separation."""
    source = (
        "apiVersion: ai-skills.dev/v1\npublisher: {id: example}\n"
        "exports: []\nvendors:\n  - id: first\n"
        '    repo: owner/first\n    sha: "'
        + "a" * 40
        + '"\n    branch: "main"'
        + (" " if separated else "")
        + "#comment"
        + line_ending
    )
    result = (
        subprocess.run(  # nosec B603 B607 - fixed parser, no shell/network/vendor code
            [
                "bun",
                str(ROOT / "tests/fixtures/manifest/renovate-parse.ts"),
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
    if separated:
        assert_that(read_document(path)["vendors"][0]["branch"]).is_equal_to("main")
    else:
        with pytest.raises(
            ValueError, match="comments after quoted scalars require whitespace"
        ):
            read_document(path)
