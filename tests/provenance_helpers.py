"""Self-contained X to Y to Z snapshots with no network or vendor execution."""

import json
import shutil
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures/provenance/two-hop"


def refresh_index(root: Path) -> None:
    """Update fixture declarations after an intentional payload edit.

    Args:
        root: Self-contained x/y/z snapshots.
    """
    # Plugin discovery also runs in the deliberately engine-free spike harness.
    from ai_skills_engine.inventory.payload import payload_files, tree_digest

    path = root / "y/ai-skills.lineage.json"
    records = json.loads(path.read_text())
    for record in records:
        for hop in record["lineage"]:
            hop["treeDigest"] = "sha256:" + tree_digest(
                payload_files(root / hop["publisher"] / hop["path"])
            )
    path.write_text(json.dumps(records, sort_keys=True))


def omit_shared_links(root: Path) -> None:
    """Isolate index authentication from independently enforced link safety.

    Args:
        root: The reusable fixture, retaining the root consumer's resource edges.
    """
    from ai_skills_engine.manifest.edit import dump_document
    from ai_skills_engine.manifest.load import read_document

    path = root / "y/ai-skills.yaml"
    document = read_document(path)
    for item in document["packages"][0]["capabilities"]:
        item.pop("resources", None)
        payload = root / "y" / item["path"] / "SKILL.md"
        payload.write_text(
            "\n".join(
                line
                for line in payload.read_text().splitlines()
                if not line.startswith("[Shared helper]")
            )
            + "\n"
        )
    path.write_text(dump_document(document))
    refresh_index(root)


def unbound_copy(root: Path) -> None:
    """Place equal resource bytes locally without declaring a publication hop.

    Args:
        root: Isolated x/y/z snapshot fixture.
    """
    copied = root / "z/_shared"
    copied.mkdir()
    (copied / "copied.py").write_bytes((root / "y/_shared/copied.py").read_bytes())
    cap = root / "z/skills/first/SKILL.md"
    cap.write_text(cap.read_text() + "\n[Unbound copy](../../_shared/copied.py).\n")


def change_policy(
    *,
    root: Path,
    mode: str = "strict",
    accept: bool = False,
    deny: tuple[str, ...] = (),
) -> None:
    """Set only the final consumer's provenance decisions.

    Args:
        root: Final consumer snapshot.
        mode: Provenance strictness.
        accept: Whether independent authorship claims may clear missing lineage.
        deny: Consumer origin vetoes.
    """
    from ai_skills_engine.manifest.edit import dump_document
    from ai_skills_engine.manifest.load import read_document

    path = root / "ai-skills.yaml"
    document = read_document(path)
    document["policy"] = {
        "provenance": {"mode": mode, "acceptAttestations": accept},
        "deny": {"origins": list(deny)},
    }
    path.write_text(dump_document(document))


def missing_copy(
    *, root: Path, statement: bool = False, statement_path: str = "proof.txt"
) -> None:
    """Copy from a declared pin's unselected documentation with no ancestry.

    Args:
        root: Fixture containing x/y/z snapshots.
        statement: Publish a descriptive claim on the copied file.
        statement_path: Payload-relative attestation path.
    """
    from ai_skills_engine.manifest.edit import dump_document
    from ai_skills_engine.manifest.load import read_document

    original = root / "x/docs/full-tree.txt"
    original.parent.mkdir(exist_ok=True)
    original.write_text("Shared fixture documentation outside all capability roots.\n")
    copy = root / "y/skills/copy"
    copy.mkdir(parents=True)
    (copy / "SKILL.md").write_text(
        "---\nname: copy\ndescription: Fixture.\n---\nIndependent wrapper.\n"
    )
    shutil.copyfile(src=original, dst=copy / "proof.txt")
    path = root / "y/ai-skills.yaml"
    document = read_document(path)
    document["packages"][0]["capabilities"].append(
        {"id": "copy", "path": "skills/copy"}
    )
    if statement:
        document.setdefault("overrides", {})["attestations"] = [
            {
                "capability": "y/tools:skill/copy",
                "path": statement_path,
                "independentlyAuthored": True,
                "reason": "Independently composed fixture text.",
            }
        ]
    path.write_text(dump_document(document))


def vendor_roots(root: Path) -> dict[str, Path]:
    """Return all declared offline pins in the reusable fixture.

    Args:
        root: Fixture directory.

    Returns:
        CLI-compatible nested vendor aliases.
    """
    return {"y": root / "y", "y/x": root / "x"}


@pytest.fixture
def provenance_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy deterministic snapshots and fail on accidental network access.

    Args:
        tmp_path: Isolated writable test root.
        monkeypatch: Network guard.

    Returns:
        Fixture root containing x, y and z.
    """

    def forbidden(*args: object, **kwargs: object) -> None:
        """Reject all network access in provenance unit tests."""
        pytest.fail("Provenance tests must remain offline")

    monkeypatch.setattr("socket.socket.connect", forbidden)
    root = tmp_path / "two-hop"
    shutil.copytree(src=FIXTURE, dst=root)
    return root
