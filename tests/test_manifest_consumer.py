"""Require real marketplace acceptance before publishing either legacy registry."""

import shutil
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.generate import marketplace
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.legacy import (
    legacy_documents,
    render_legacy,
    write_legacy,
)
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.validate import validate_document

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ("baseline", None),
        ("id-key-mismatch", "must match the group key"),
        ("duplicate-skill", "listed in both"),
        ("missing-skill", "missing skills: branch"),
        ("unknown-skill", "references missing skill dirs: unknown"),
    ],
)
def test_actual_marketplace_acceptance_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str, error: str | None
) -> None:
    """Matched source trees expose semantic failures without narrowing the schema."""
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
    assert_that(validate_document(data)).is_empty()
    (tmp_path / "ai-skills.yaml").write_text(dump_document(data))
    args = ["--repo-root", str(tmp_path), "manifest"]
    assert_that(cli.main([*args, "validate"])).is_zero()
    # Independently reproduce the actual consumer's acceptance of these declarations.
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    shutil.copytree(src=tmp_path / "skills", dst=consumer / "skills")
    shutil.copy2(src=ROOT / "pyproject.toml", dst=consumer / "pyproject.toml")
    for name, document in legacy_documents(data).items():
        (consumer / name).write_text(dump_document(document))
    if error:
        with pytest.raises(ValueError, match=error):
            marketplace.generate_marketplace(repo_root=consumer)
    else:
        assert_that(marketplace.main(["--repo-root", str(consumer)])).is_zero()
        assert_that(
            marketplace.main(["--repo-root", str(consumer), "--check"])
        ).is_zero()
    sentinels = {
        tmp_path / name: f"# unchanged sentinel {name}\n".encode()
        for name in ("bundles.yaml", "vendors.yaml")
    }
    for path, content in sentinels.items():
        path.write_bytes(content)
    writes: list[Path] = []
    write_bytes = Path.write_bytes

    def observe_write(path: Path, content: bytes) -> int:
        """Observe actual destination writes while retaining scratch consumer I/O."""
        if path in sentinels:
            writes.append(path)
        return write_bytes(path, content)

    monkeypatch.setattr(Path, "write_bytes", observe_write)
    for operation in (
        lambda: render_legacy(tmp_path),
        lambda: write_legacy(tmp_path),
        lambda: write_legacy(tmp_path, check=True),
    ):
        if error:
            with pytest.raises(ValueError, match=error):
                operation()
            for path, content in sentinels.items():
                assert_that(path.read_bytes()).is_equal_to(content)
        else:
            operation()
    for check in ([], ["--check"]):
        assert_that(cli.main([*args, "legacy", *check])).is_equal_to(1 if error else 0)
        if error:
            for path, content in sentinels.items():
                assert_that(path.read_bytes()).is_equal_to(content)
    if error:
        assert_that(writes).is_empty()
    if not error:
        assert_that(marketplace.main(["--repo-root", str(tmp_path)])).is_zero()
        assert_that(
            marketplace.main(["--repo-root", str(tmp_path), "--check"])
        ).is_zero()
        for name in ("bundles.yaml", "vendors.yaml"):
            assert_that((tmp_path / name).read_bytes()).is_equal_to(
                (ROOT / name).read_bytes()
            )
