"""Keep the permissive production parser distinct from strict manifest publication."""

from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.manifest.legacy import render_legacy, write_legacy
from ai_skills_engine.manifest.load import load_manifest

pytest_plugins = ("manifest_helpers",)
pytestmark = pytest.mark.usefixtures("author_skills")

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("line_ending", ["\n", "\r\n", ""])
def test_unseparated_comment_rejected_before_publication(
    tmp_path: Path,
    line_ending: str,
) -> None:
    """The Python publication boundary rejects invalid comments without Bun."""
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
