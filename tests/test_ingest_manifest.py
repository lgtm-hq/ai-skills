"""Ingestion policy survives the actual manifest/legacy/registry boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.manifest.codec import encode
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import load_manifest, read_document
from ai_skills_engine.manifest.validate import validate_document
from ai_skills_engine.registry.registry import load_registry

pytest_plugins = ["manifest_helpers", "inventory_helpers"]
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def policy_author(tmp_path: Path, author_skills: None) -> Path:
    """Use the real author manifest and payloads for compatibility publication.

    Args:
        tmp_path: Isolated author directory.
        author_skills: Actual first-party payload fixture.

    Returns:
        Author root with consumer-owned synthetic acknowledgements.
    """
    del author_skills
    document = read_document(ROOT / "ai-skills.yaml")
    document["vendors"][0]["ingestAllow"] = [
        {
            "path": "skills/synthetic/SKILL.md",
            "rule": "aws-access-key-id",
            "sha256": "a" * 64,
            "reason": "Synthetic documentation acknowledgement",
        }
    ]
    document["vendors"][0]["ingestLimits"] = {
        "fileBytes": 6 * 1024 * 1024,
        "reason": "Reviewed synthetic override",
    }
    document["overrides"] = {
        "ingestAllow": [
            {
                "path": "skills/synthetic/SKILL.md",
                "rule": "pem-private-key",
                "sha256": "b" * 64,
                "reason": "Synthetic own-package acknowledgement",
            }
        ]
    }
    (tmp_path / "ai-skills.yaml").write_text(dump_document(document))
    return tmp_path


def test_actual_manifest_projection_carries_policy_and_remains_byte_stable(
    policy_author: Path,
) -> None:
    """Typed models and both production compatibility readers retain the policy."""
    source = policy_author / "ai-skills.yaml"
    before = source.read_bytes()
    model = load_manifest(source)
    assert_that(encode(model.vendors[0].ingest_allow)[0]["sha256"]).is_equal_to(
        "a" * 64
    )
    limits = model.vendors[0].ingest_limits
    if limits is None or model.overrides is None:
        pytest.fail("typed ingestion policy was lost")
    assert_that(limits.file_bytes).is_equal_to(6 * 1024 * 1024)
    assert_that(model.overrides.ingest_allow[0].rule).is_equal_to("pem-private-key")
    args = ["manifest", "legacy", "--repo-root", str(policy_author)]
    assert_that(cli.main(args)).is_zero()
    derived = load_registry(registry_path=policy_author / "vendors.yaml")[0]
    assert_that(derived.ingest_allow).is_equal_to(model.vendors[0].ingest_allow)
    assert_that(derived.ingest_limits).is_equal_to(model.vendors[0].ingest_limits)
    first = {
        name: (policy_author / name).read_bytes()
        for name in ("bundles.yaml", "vendors.yaml")
    }
    assert_that(cli.main([*args, "--check"])).is_zero()
    assert_that(cli.main(args)).is_zero()
    assert_that(source.read_bytes()).is_equal_to(before)
    assert_that(
        {name: (policy_author / name).read_bytes() for name in first}
    ).is_equal_to(first)


@pytest.mark.parametrize(
    "field,value",
    [
        ("ingestLimits", {"fileBytes": True, "reason": "synthetic"}),
        ("ingestLimits", {"fileBytes": 1, "reason": " "}),
        ("ingestLimits", {"fileBytes": 0, "reason": "synthetic"}),
        ("ingestLimits", {"unknown": 1, "reason": "synthetic"}),
        (
            "ingestAllow",
            [
                {
                    "path": "../escape",
                    "rule": "aws-access-key-id",
                    "sha256": "a" * 64,
                    "reason": "synthetic",
                }
            ],
        ),
        (
            "ingestAllow",
            [
                {
                    "path": "skills/a",
                    "rule": "unknown",
                    "sha256": "a" * 64,
                    "reason": "synthetic",
                }
            ],
        ),
    ],
)
def test_invalid_policy_fails_before_legacy_writes(
    policy_author: Path, field: str, value: Any
) -> None:
    """The schema rejects invalid extensions before either derived file changes."""
    path = policy_author / "ai-skills.yaml"
    document = read_document(path)
    document["vendors"][0][field] = value
    path.write_text(dump_document(document))
    assert_that(validate_document(document)).is_not_empty()
    for name in ("bundles.yaml", "vendors.yaml"):
        (policy_author / name).write_bytes(b"original sentinel\r\n")
    assert_that(
        cli.main(["manifest", "legacy", "--repo-root", str(policy_author)])
    ).is_equal_to(1)
    for name in ("bundles.yaml", "vendors.yaml"):
        assert_that((policy_author / name).read_bytes()).is_equal_to(
            b"original sentinel\r\n"
        )


@pytest.mark.parametrize("fetched", [False, True])
def test_inventory_vendor_content_checks_cover_both_modes(
    inventory_repo: tuple[Path, Path],
    fetched: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both public ingestion paths report private findings for selected bytes."""
    from inventory_helpers import inventory_snapshot, inventory_tarball

    from ai_skills_engine.bake import vendor_plugins

    root, vendor = inventory_repo
    # Repeated synthetic characters are not a usable credential.
    sample = b"AKIA" + b"A" * 16
    path = vendor / "skills/help/synthetic.txt"
    path.write_bytes(b"Synthetic example\n" + sample)
    before = inventory_snapshot(root, vendor)
    if fetched:
        monkeypatch.setattr(
            vendor_plugins,
            "_http_get_bytes",
            lambda **_kwargs: inventory_tarball(vendor),
        )
    args = ["--fetch-vendors"] if fetched else ["--vendor-root", f"vendor={vendor}"]
    assert_that(
        cli.main(["inventory", "--repo-root", str(root), "--json", *args])
    ).is_equal_to(1)
    output = capsys.readouterr()
    assert_that(output.out + output.err).contains("aws-access-key-id").does_not_contain(
        sample.decode()
    )
    assert_that(inventory_snapshot(root, vendor)).is_equal_to(before)
