"""Prove the actual offline loading boundary cannot adopt vendor authority."""

from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import load_consumer, read_document

FIXTURES = Path(__file__).parent / "fixtures" / "manifest"


@pytest.fixture
def consumer_and_vendor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    """Declare an adversarial local vendor and forbid every HTTP fetch.

    Args:
        tmp_path: Isolated consumer and vendor roots.
        monkeypatch: Network guard.

    Returns:
        Consumer manifest and local vendor checkout.
    """

    def no_network(*args: object, **kwargs: object) -> None:
        """Fail any accidental network access."""
        pytest.fail("Manifest loading must be offline")

    monkeypatch.setattr("socket.socket.connect", no_network)
    data = read_document(FIXTURES / "valid.yaml")
    data["vendors"][0].pop("mapping")
    data["vendors"][0]["include"] = []
    data["exports"] = ["tools", "actual/upstream-tools"]
    # This fixture isolates vendor authority. Supply actual local payloads and
    # omit the unrelated edge selectors from the schema-only positive fixture.
    data["packages"][0]["capabilities"][0].update(requires=[], related=[])
    (tmp_path / "skills/run").mkdir(parents=True)
    (tmp_path / "skills/run/SKILL.md").write_text(
        "---\nname: run\ndescription: Boundary fixture.\n---\n"
    )
    (tmp_path / "NOTICE.md").write_text("Boundary fixture notice.\n")
    path = tmp_path / "ai-skills.yaml"
    path.write_text(dump_document(data))
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "ai-skills.yaml").write_text(
        dump_document(
            {
                "apiVersion": "ai-skills.dev/v1",
                "publisher": {"id": "actual"},
                "packages": [{"id": "upstream-tools"}],
                "exports": ["upstream-tools"],
                "policy": {"provenance": {"mode": "warn", "acceptAttestations": True}},
                "overrides": {
                    "attestations": [
                        {
                            "capability": "actual/upstream-tools:skill/run",
                            "path": "trust.py",
                            "independentlyAuthored": True,
                            "reason": "Trust me",
                        }
                    ]
                },
                "x-trust": {"execute": "trust.py"},
            }
        )
    )
    (vendor / "trust.py").write_text("raise RuntimeError('vendor executed')\n")
    return path, vendor


def test_vendor_authority_removed_at_loading_boundary(
    consumer_and_vendor: tuple[Path, Path],
) -> None:
    """Vendor IDs use its publisher while its policy/trust never enter imports."""
    path, vendor = consumer_and_vendor
    consumer, imports, diagnostics = load_consumer(
        path, vendor_roots={"upstream": vendor}
    )
    assert_that(consumer.policy.provenance.mode).is_equal_to("strict")
    assert_that(consumer.policy.provenance.accept_attestations).is_false()
    assert_that(consumer.vendors[0].include).is_equal_to(())
    assert_that(imports["upstream"].publisher.id).is_equal_to("actual")
    assert_that(imports["upstream"].policy).is_none()
    assert_that(imports["upstream"].overrides).is_none()
    assert_that(imports["upstream"].extensions).is_empty()
    assert_that([item.code for item in diagnostics]).is_equal_to(
        ["vendor-authority-ignored"] * 3
    )
    assert_that(all(item.warning for item in diagnostics)).is_true()
    assert_that(
        cli.main(
            [
                "--repo-root",
                str(path.parent),
                "manifest",
                "validate",
                "--vendor-root",
                f"upstream={vendor}",
            ]
        )
    ).is_zero()


def test_mapping_rejected_for_real_manifest_vendor(
    consumer_and_vendor: tuple[Path, Path],
) -> None:
    """Local loading detects the vendor manifest rather than trusting a flag."""
    path, vendor = consumer_and_vendor
    data = read_document(path)
    data["vendors"][0]["mapping"] = {"skillRoots": ["skills"]}
    path.write_text(dump_document(data))
    _, _, diagnostics = load_consumer(path, vendor_roots={"upstream": vendor})
    assert_that([item.code for item in diagnostics if not item.warning]).contains(
        "mapping-on-manifest-vendor"
    )
    assert_that(
        cli.main(
            [
                "--repo-root",
                str(path.parent),
                "manifest",
                "validate",
                "--vendor-root",
                f"upstream={vendor}",
            ]
        )
    ).is_equal_to(1)
