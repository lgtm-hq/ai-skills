"""Public artifact command and reviewed-digest drift boundaries."""

import json
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.artifacts.drift import check_inputs, read_digests

pytest_plugins = ["artifact_helpers", "ingest_helpers"]


def test_public_build_and_drift(
    artifact_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Actual commands generate commitments and reject local or reviewed drift."""
    args = ["--repo-root", str(artifact_repo), "build"]
    assert_that(cli.main([*args, "--write-digests"])).is_zero()
    path = artifact_repo / "artifact-digests.json"
    reviewed = path.read_bytes()
    assert_that(cli.main([*args, "--check"])).is_zero()
    assert_that(cli.main([*args, "--check-inputs"])).is_zero()
    source = artifact_repo / "shared/data/input.txt"
    source.write_text(source.read_text() + "Changed fixture bytes.\n")
    assert_that(cli.main([*args, "--check"])).is_equal_to(1)
    assert_that(cli.main([*args, "--check-inputs"])).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("rebuilt artifact digests")
    assert_that(path.read_bytes()).is_equal_to(reviewed)
    assert_that(cli.main([*args, "--write-digests"])).is_zero()
    data = read_digests(path)
    data["packages"]["fixture/tools"]["artifactDigest"] = "sha256:" + "0" * 64
    path.write_text(json.dumps(data))
    assert_that(cli.main([*args, "--check"])).is_equal_to(1)


def test_bake_command_alias_and_missing_vendor(
    artifact_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bake artifacts uses the same writer and fails closed on missing pins."""
    assert_that(
        cli.main(["bake", "artifacts", "--repo-root", str(artifact_repo)])
    ).is_zero()
    manifest = artifact_repo / "ai-skills.yaml"
    manifest.write_text(
        manifest.read_text()
        + '\nvendors:\n  - id: absent\n    repo: fixture/absent\n    sha: "'
        + "a" * 40
        + '"\n'
    )
    assert_that(cli.main(["build", "--repo-root", str(artifact_repo)])).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("selection.vendor-unavailable")


def test_unknown_digest_format_fails(artifact_repo: Path) -> None:
    """Unknown formats and duplicate keys cannot become a reviewed commitment."""
    path = artifact_repo / "artifact-digests.json"
    path.write_text('{"artifactFormat": 7}')
    with pytest.raises(ValueError, match="Unsupported"):
        check_inputs(root=artifact_repo, path=path)
    path.write_text('{"artifactFormat": 1, "artifactFormat": 1}')
    with pytest.raises(ValueError, match="duplicate"):
        read_digests(path)


def test_explicit_pinned_acquisition_uses_real_offline_transport_boundary(
    artifact_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fetch authorization reuses bounded archive ingestion without real network."""
    import io
    import tarfile

    from ai_skills_engine.bake import vendor_plugins
    from ai_skills_engine.manifest.edit import dump_document

    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w:gz") as archive:
        archive.add(artifact_repo, arcname="root")
    received: list[str] = []

    def transport(**kwargs: object) -> bytes:
        """Supply synthetic pinned archive bytes through the existing transport."""
        received.append(str(kwargs["path"]))
        return archive_bytes.getvalue()

    monkeypatch.setattr(vendor_plugins, "_http_get_bytes", transport)
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "ai-skills.yaml").write_text(
        dump_document(
            {
                "apiVersion": "ai-skills.dev/v1",
                "publisher": {"id": "consumer", "repo": "fixture/consumer"},
                "vendors": [
                    {"id": "upstream", "repo": "fixture/artifacts", "sha": "a" * 40}
                ],
                "policy": {"provenance": {"mode": "strict"}},
            }
        )
    )
    args = ["build", "--repo-root", str(consumer)]
    assert_that(cli.main([*args, "--fetch-vendors", "--write-digests"])).is_zero()
    assert_that(received).is_equal_to(["/repos/fixture/artifacts/tarball/" + "a" * 40])
    assert_that(cli.main([*args, "--fetch-vendors", "--check"])).is_zero()
    assert_that(received).is_length(2)


def test_recursive_acquisition_fails_before_fetch(
    artifact_repo: Path, tmp_path: Path
) -> None:
    """Recursive source declarations never start an unbounded acquisition walk."""
    from ai_skills_engine.artifacts.acquire import acquire_inputs
    from ai_skills_engine.manifest.edit import dump_document
    from ai_skills_engine.manifest.load import read_document

    document = read_document(artifact_repo / "ai-skills.yaml")
    document["vendors"] = [
        {"id": "upstream", "repo": "fixture/recursive", "sha": "a" * 40}
    ]
    (artifact_repo / "ai-skills.yaml").write_text(dump_document(document))
    with pytest.raises(ValueError, match="Recursive pinned"):
        acquire_inputs(
            root=artifact_repo,
            supplied={"upstream": artifact_repo, "upstream/upstream": artifact_repo},
            temporary=tmp_path / "acquired",
        )
    assert_that((tmp_path / "acquired").exists()).is_false()


def test_compatibility_offline_bake_preserves_pristine_input(
    ingest_repo: tuple[Path, Path, object],
) -> None:
    """The CLI's offline mapping never prunes the caller's source snapshots."""
    from ai_skills_engine.bake import vendor_plugins
    from ai_skills_engine.registry.registry import load_registry

    root, source, _vendor = ingest_repo
    (source / "CLAUDE.md").write_text("Synthetic vendor navigation.\n")
    alias = source / "AGENTS.md"
    alias.symlink_to("CLAUDE.md")
    vendor = load_registry(registry_path=root / "vendors.yaml")[0]
    assert_that(
        vendor_plugins.main(
            ["--repo-root", str(root), "--vendor-tree", f"{vendor.id}={source}"]
        )
    ).is_zero()
    assert_that(alias.is_symlink()).is_true()
    assert_that(alias.readlink().as_posix()).is_equal_to("CLAUDE.md")
    assert_that(vendor_plugins.check(repo_root=root)).is_zero()
