"""Require real legacy-consumer acceptance before publishing either registry.

Since #575 the committed marketplaces are rendered from the artifact index
(``ai-skills.yaml``), never from ``bundles.yaml``. The README generator, through
``load_validated_bundles``, is the remaining real reader of the legacy bundle
declarations, so it is the consumer whose acceptance publication reproduces.
The artifact-fed marketplace path is checked against the equivalent manifest
defects separately.
"""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.envelopes import rules
from ai_skills_engine.generate import marketplace, readme
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.legacy import (
    legacy_documents,
    render_legacy,
    write_legacy,
)
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.validate import validate_document

ROOT = Path(__file__).resolve().parents[1]


def _author_tree(root: Path, change: str) -> dict[str, Any]:
    """Write real skills plus the real manifest carrying one semantic defect.

    Args:
        root: Empty author repository root.
        change: Defect to apply, or ``baseline`` for none.

    Returns:
        The schema-valid manifest data written to ``ai-skills.yaml``.
    """
    shutil.copytree(src=ROOT / "skills", dst=root / "skills")
    shutil.copy2(src=ROOT / "pyproject.toml", dst=root / "pyproject.toml")
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
        shutil.copytree(src=ROOT / "skills/branch", dst=root / "skills/unknown")
    assert_that(validate_document(data)).is_empty()
    (root / "ai-skills.yaml").write_text(dump_document(data))
    assert_that(cli.main(["--repo-root", str(root), "manifest", "validate"])).is_zero()
    if change == "unknown-skill":
        # Inventory validation needs real payloads. Remove this genuine copied
        # skill afterward: publication must still check the current source tree.
        shutil.rmtree(root / "skills/unknown")
    return data


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
    data = _author_tree(tmp_path, change)
    args = ["--repo-root", str(tmp_path), "manifest"]
    # Independently reproduce the actual legacy consumer's acceptance of these
    # declarations: the README generator's validated bundles.yaml reader.
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    shutil.copytree(src=tmp_path / "skills", dst=consumer / "skills")
    shutil.copy2(src=ROOT / "pyproject.toml", dst=consumer / "pyproject.toml")
    shutil.copy2(src=ROOT / "README.md", dst=consumer / "README.md")
    readme_bytes = (consumer / "README.md").read_bytes()
    for name, document in legacy_documents(data).items():
        (consumer / name).write_text(dump_document(document))
    if error:
        with pytest.raises(ValueError, match=error):
            marketplace.load_validated_bundles(repo_root=consumer)
        for check in ([], ["--check"]):
            with pytest.raises(ValueError, match=error):
                readme.main(["--repo-root", str(consumer), *check])
            assert_that((consumer / "README.md").read_bytes()).is_equal_to(readme_bytes)
    else:
        marketplace.load_validated_bundles(repo_root=consumer)
        assert_that(readme.main(["--repo-root", str(consumer), "--check"])).is_zero()
        assert_that(readme.main(["--repo-root", str(consumer)])).is_zero()
        assert_that((consumer / "README.md").read_bytes()).is_equal_to(readme_bytes)
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


def _committed_marketplaces() -> dict[str, Any]:
    """Return every committed repo-root marketplace, parsed.

    Returns:
        Repository-relative marketplace path to its parsed document.
    """
    return {
        str(host["marketplace"]["path"]): json.loads(
            (ROOT / host["marketplace"]["path"]).read_text(encoding="utf-8")
        )
        for host in rules()["hosts"].values()
    }


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ("baseline", None),
        # The artifact has one package identity; x-legacy-group is never read.
        ("id-key-mismatch", None),
        ("duplicate-skill", "Reserved destination skill/branch"),
        # An unpackaged skill is unpublished, never delivered by a marketplace.
        ("missing-skill", None),
        ("unknown-skill", "Missing or unsupported payload: skills/unknown"),
    ],
)
def test_artifact_marketplace_rejects_equivalent_manifest_defects(
    tmp_path: Path, change: str, error: str | None
) -> None:
    """The artifact-fed marketplace rejects each defect or cannot express it."""
    _author_tree(tmp_path, change)
    paths = sorted(_committed_marketplaces())
    if error:
        with pytest.raises(ValueError, match=error):
            marketplace.generate_marketplace(repo_root=tmp_path)
        for check in (["--check"], []):
            assert_that(
                marketplace.main(["--repo-root", str(tmp_path), *check])
            ).is_equal_to(1)
        for path in paths:
            assert_that(str(tmp_path / path)).does_not_exist()
        return
    expected = _committed_marketplaces()
    for document in expected.values():
        for plugin in document["plugins"]:
            if change == "id-key-mismatch" and plugin["name"] == "git-pr":
                plugin["name"] = "git-workflow"
            if change == "missing-skill" and "skills" in plugin:
                plugin["skills"] = [
                    skill for skill in plugin["skills"] if skill != "./skills/branch"
                ]
    rendered = marketplace.repo_marketplaces(repo_root=tmp_path)
    assert_that(sorted(rendered)).is_equal_to(paths)
    for path, content in rendered.items():
        assert_that(json.loads(content)).is_equal_to(expected[path])
        if change == "baseline":
            assert_that(content).is_equal_to((ROOT / path).read_bytes())
        if change == "missing-skill":
            assert_that(content.decode("utf-8")).does_not_contain("skills/branch")
    assert_that(marketplace.main(["--repo-root", str(tmp_path)])).is_zero()
    assert_that(marketplace.main(["--repo-root", str(tmp_path), "--check"])).is_zero()
