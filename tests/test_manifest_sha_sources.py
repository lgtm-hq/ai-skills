"""Enforce the owner's SHA source contract before compatibility publication."""

from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.manifest.legacy import render_legacy, write_legacy
from ai_skills_engine.manifest.load import load_manifest
from ai_skills_engine.registry.registry import load_unique_yaml_text

ROOT = Path(__file__).resolve().parents[1]
OLD = "a" * 40


@pytest.mark.parametrize(
    "scalar",
    [
        '"' + r"\u0061" * 40 + '"',
        f"&pin {OLD}",
        "*shared",
        f"!!str {OLD}",
        f"!custom {OLD}",
        f">-\n      {OLD}\n",
        f"|-\n      {OLD}\n",
        '"' + OLD[:20] + "\\\n      " + OLD[20:] + '"',
    ],
    ids=[
        "escaped-sha",
        "anchor",
        "shared-alias",
        "tag",
        "custom-tag",
        "folded",
        "literal",
        "escaped-line",
    ],
)
@pytest.mark.parametrize(
    "existing", [False, True], ids=["absent-registries", "existing-registries"]
)
def test_sha_source_rejected_before_any_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scalar: str,
    existing: bool,
) -> None:
    """Every entry point rejects unsafe SHA spellings with zero registry writes."""
    source = (
        f"x-shared: &shared {OLD}\n"
        "apiVersion: ai-skills.dev/v1\npublisher: {id: example}\nexports: []\n"
        "vendors:\n  - id: first\n    repo: owner/first\n"
        f"    sha: '{OLD}'\n    branch: main\n"
        "  - id: second\n    repo: owner/second\n"
        f"    sha: {scalar}\n    branch: main\n"
    )
    path = tmp_path / "ai-skills.yaml"
    path.write_text(source)
    destinations = [tmp_path / name for name in ("bundles.yaml", "vendors.yaml")]
    if existing:
        for destination in destinations:
            destination.write_bytes(b"sentinel\n")
    original_write = Path.write_bytes

    def guard(destination: Path, data: bytes) -> int:
        """Fail even if publication would later restore the original bytes."""
        if destination in destinations:
            pytest.fail(f"Rejected SHA attempted registry write: {destination}")
        return original_write(destination, data)

    monkeypatch.setattr(Path, "write_bytes", guard)
    message = r"/vendors/1/sha.*second.*direct, unescaped 40-hex scalar"
    for operation in (
        lambda: load_manifest(path),
        lambda: render_legacy(tmp_path),
        lambda: write_legacy(tmp_path),
        lambda: write_legacy(tmp_path, check=True),
    ):
        with pytest.raises(ValueError, match=message):
            operation()
    args = ["--repo-root", str(tmp_path), "manifest"]
    for command in (["validate"], ["legacy"], ["legacy", "--check"]):
        assert_that(cli.main([*args, *command])).is_equal_to(1)
        assert_that(capsys.readouterr().out).contains(
            "/vendors/1/sha",
            "second",
            "direct, unescaped 40-hex scalar",
            "plain or ordinary single/double quoted",
            "anchors, aliases or tags",
        )
    for destination in destinations:
        if existing:
            assert_that(destination.read_bytes()).is_equal_to(b"sentinel\n")
        else:
            assert_that(destination.exists()).is_false()


@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_direct_sha_and_other_yaml_spellings_remain_valid(
    tmp_path: Path,
    quote: str,
) -> None:
    """Only SHA spelling narrows: escaped repo/branch and other YAML stay valid."""
    path = tmp_path / "ai-skills.yaml"
    path.write_text(
        "apiVersion: ai-skills.dev/v1\npublisher: {id: example}\nexports: []\n"
        "x-shared: &shared {anything: [1, true]}\nx-alias: *shared\n"
        'vendors:\n - branch: "ma\\u0069n"\n'
        '   repo: "\\u006fwner/project"\n'
        f"   sha: {quote}{OLD}{quote} # ordinary scalar\n   id: first\n"
    )
    vendor = load_manifest(path).vendors[0]
    assert_that((vendor.sha, vendor.repo, vendor.branch)).is_equal_to(
        (OLD, "owner/project", "main"),
    )


def test_escaped_and_aliased_sha_decode_to_valid_digests() -> None:
    """Decoded-only validation cannot enforce the source contract."""
    data = load_unique_yaml_text(
        text=f'x-shared: &shared {OLD}\nescaped: "'
        + r"\u0061" * 40
        + '"\nalias: *shared\n',
    )
    assert_that(data["escaped"]).is_equal_to(OLD)
    assert_that(data["alias"]).is_equal_to(OLD)


def test_decimal_only_sha_names_the_quoting_fix(tmp_path: Path) -> None:
    """A plain all-digit SHA parses as a number; the error says to quote it."""
    digits = "1" + "2" * 39
    path = tmp_path / "ai-skills.yaml"
    path.write_text(
        "apiVersion: ai-skills.dev/v1\npublisher: {id: example}\nexports: []\n"
        f"vendors:\n  - id: first\n    repo: owner/first\n    sha: {digits}\n"
        "    branch: main\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError, match=f'decimal-only SHA .*quote it: sha: "{digits}"'
    ):
        load_manifest(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(digits, f'"{digits}"'),
        encoding="utf-8",
    )
    assert_that(load_manifest(path).vendors[0].sha).is_equal_to(digits)
