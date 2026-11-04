"""Public artifact commands and resolution-lock drift boundaries."""

import json
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.lockfile import read_lock

pytest_plugins = ["artifact_helpers", "ingest_helpers"]


def test_public_lock_build_and_drift(
    artifact_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Actual commands generate the lock and reject local or reviewed drift."""
    args = ["--repo-root", str(artifact_repo)]
    assert_that(cli.main([*args, "lock"])).is_zero()
    path = artifact_repo / "ai-skills.lock"
    reviewed = path.read_bytes()
    assert_that(cli.main([*args, "lock", "--check"])).is_zero()
    assert_that(cli.main([*args, "lock", "--check", "--inputs-only"])).is_zero()
    assert_that(cli.main([*args, "build"])).is_zero()
    source = artifact_repo / "shared/data/input.txt"
    source.write_text(source.read_text() + "Changed fixture bytes.\n")
    capsys.readouterr()
    for command in (
        ["lock", "--check"],
        ["lock", "--check", "--inputs-only"],
        ["build"],
    ):
        assert_that(cli.main([*args, *command])).is_equal_to(1)
        assert_that(capsys.readouterr().err).contains("local author inputs changed")
    assert_that(path.read_bytes()).is_equal_to(reviewed)
    assert_that(cli.main([*args, "lock"])).is_zero()
    data = json.loads(path.read_text())
    data["packages"][0]["artifactDigest"] = "sha256:" + "0" * 64
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    assert_that(cli.main([*args, "lock", "--check"])).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("rebuilt ai-skills.lock")
    assert_that(cli.main([*args, "build"])).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains(
        "artifactDigest locked sha256:" + "0" * 64, "nothing was published"
    )


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
    assert_that(
        cli.main(["bake", "artifacts", "--repo-root", str(artifact_repo)])
    ).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("selection.vendor-unavailable")


def test_version_bump_requires_regenerating_tar_commitment(
    artifact_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A new installed builder changes tar identity while preserving tree identity."""
    args = ["--repo-root", str(artifact_repo)]
    builder = "1.2.3"
    monkeypatch.setattr("ai_skills_engine.artifact.version", lambda _name: builder)
    assert_that(cli.main([*args, "lock"])).is_zero()
    path = artifact_repo / "ai-skills.lock"
    before = read_lock(path)
    builder = "1.2.4"
    for command in (["lock", "--check"], ["build"]):
        assert_that(cli.main([*args, *command])).is_equal_to(1)
        assert_that(capsys.readouterr().err).contains(
            "built by engine 1.2.3", "this engine is 1.2.4"
        )
    assert_that(cli.main([*args, "lock"])).is_zero()
    after = read_lock(path)
    assert_that(after.manifest).is_equal_to(before.manifest)
    assert_that([item.id for item in after.packages]).is_equal_to(
        [item.id for item in before.packages]
    )
    for old, new in zip(before.packages, after.packages, strict=True):
        assert_that(new.tree_digest).is_equal_to(old.tree_digest)
        assert_that(new.artifact_digest).is_not_equal_to(old.artifact_digest)
    assert_that(cli.main([*args, "build"])).is_zero()
    index = json.loads((artifact_repo / "dist/artifacts/index.json").read_text())
    assert_that(index["engineVersion"]).is_equal_to(builder)
    assert_that(cli.main([*args, "lock", "--check"])).is_zero()


def test_explicit_pinned_acquisition_uses_real_offline_transport_boundary(
    artifact_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lock reuses bounded archive ingestion once; check and build stay offline."""
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
    args = ["--repo-root", str(consumer)]
    assert_that(cli.main([*args, "lock"])).is_zero()
    assert_that(received).is_equal_to(["/repos/fixture/artifacts/tarball/" + "a" * 40])
    for command in (["lock"], ["lock", "--fetch"], ["lock", "--check"], ["build"]):
        assert_that(cli.main([*args, *command])).is_zero()
    assert_that(received).is_length(1)
    assert_that(read_lock(consumer / "ai-skills.lock").packages).is_not_empty()


def test_recursive_acquisition_fails_before_fetch(
    artifact_repo: Path, tmp_path: Path, isolated_source_cache: Path
) -> None:
    """Recursive source declarations never start an unbounded acquisition walk."""
    from ai_skills_engine.commands.source_mode import SourceMode
    from ai_skills_engine.commands.sources import materialize_sources
    from ai_skills_engine.manifest.edit import dump_document
    from ai_skills_engine.manifest.load import read_document
    from ai_skills_engine.source_cache import SourceCache

    document = read_document(artifact_repo / "ai-skills.yaml")
    document["vendors"] = [
        {"id": "upstream", "repo": "fixture/recursive", "sha": "a" * 40}
    ]
    (artifact_repo / "ai-skills.yaml").write_text(dump_document(document))

    def fetch(**_kwargs: object) -> None:
        """Fail if the recursion guard lets any acquisition start."""
        pytest.fail("Recursive inputs must fail before fetching")

    with pytest.raises(ValueError, match="Recursive pinned"):
        materialize_sources(
            root=artifact_repo,
            cache=SourceCache(root=isolated_source_cache),
            scratch=tmp_path / "acquired",
            mode=SourceMode.RESOLVE,
            locked={},
            supplied={"upstream": artifact_repo},
            fetcher=fetch,
        )
    assert_that(list(isolated_source_cache.rglob("*.tar"))).is_length(1)


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
