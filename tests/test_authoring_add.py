"""``add`` imports pinned vendors through a local fake forge, then locks them."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that
from authoring_helpers import PINS, Forge, codes, run_cli, validate_json

from ai_skills_engine.commands import add
from ai_skills_engine.commands.mapping_scaffold import SCAFFOLD_MARKER
from ai_skills_engine.lockfile import read_lock
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document

pytest_plugins = ["authoring_helpers"]


def _add(root: Path, *arguments: str) -> tuple[int, str, str]:
    """Run ``add`` against a consumer.

    Args:
        root: Consumer repository.
        arguments: ``add`` arguments.

    Returns:
        Status, stdout and stderr.
    """
    result: tuple[int, str, str] = run_cli("add", "--repo-root", str(root), *arguments)
    return result


def _vendor(root: Path, alias: str) -> dict[str, Any]:
    """Read one declared vendor.

    Args:
        root: Consumer repository.
        alias: Vendor alias.

    Returns:
        Vendor declaration.
    """
    return next(
        item
        for item in read_document(root / "ai-skills.yaml")["vendors"]
        if item["id"] == alias
    )


def _index(root: Path) -> dict[str, dict[str, Any]]:
    """Build artifacts from the lock and index capabilities by ID.

    Args:
        root: Locked consumer repository.

    Returns:
        Capability records of the catalog index.
    """
    # A fresh output keeps the build on its create path, avoiding the engine's
    # own libc probe for an atomic exchange under the subprocess guard.
    output = root / "dist" / str(len(list(root.glob("dist/*"))))
    status, _, error = run_cli(
        "build", "--repo-root", str(root), "--output", str(output)
    )
    assert_that(status).described_as(error).is_zero()
    index = json.loads((output / "index.json").read_text())
    return {
        item["id"]: item
        for package in index["packages"]
        for item in package["capabilities"]
    }


def test_manifest_vendor_imports_upstream_exports_and_locks(
    consumer: Path, forge: Forge
) -> None:
    """A pinned entry imports exactly the exports; vendor policy is ignored."""
    status, output, error = _add(consumer, "fixture-org/manifest@v1.0.0")
    assert_that(status).described_as(error).is_zero()
    assert_that(forge.resolved).is_equal_to([("fixture-org/manifest", "v1.0.0", None)])
    assert_that(forge.fetched).is_equal_to(
        [f"fixture-org/manifest@{PINS['fixture-org/manifest']}"]
    )
    assert_that(output).contains("add: ignored upstream policy")
    assert_that(_vendor(consumer, "manifest")).is_equal_to(
        {
            "id": "manifest",
            "repo": "fixture-org/manifest",
            "sha": PINS["fixture-org/manifest"],
            "displayRef": "v1.0.0",
            "include": ["fixture-vendor/core", "fixture-vendor/crew"],
        }
    )
    text = (consumer / "ai-skills.yaml").read_text()
    assert_that(text).contains("# Consumer fixture; comments survive add.")
    lock = read_lock(consumer / "ai-skills.lock")
    assert_that([item.id for item in lock.vendors]).is_equal_to(["manifest"])
    assert_that([item.id for item in lock.packages]).is_equal_to(
        ["consumer/local", "fixture-vendor/core", "fixture-vendor/crew"]
    )
    capabilities = _index(consumer)
    assert_that(capabilities["fixture-vendor/core:skill/alpha"]).does_not_contain_key(
        "identity"
    )
    status, report = validate_json(consumer, "--strict")
    assert_that(status).described_as(json.dumps(report)).is_zero()
    assert_that([item["location"] for item in report["ignored"]]).is_equal_to(
        ["/vendors/manifest/policy"]
    )


def test_manifestless_vendor_requires_accepted_consumer_mapping(
    consumer: Path, forge: Forge
) -> None:
    """The scaffold is written but never locked until ``--accept-mapping``."""
    status, output, _ = _add(consumer, "fixture-org/manifestless")
    assert_that(status).is_equal_to(1)
    assert_that(output).contains("not locked", "--accept-mapping")
    assert_that(forge.resolved).is_equal_to([("fixture-org/manifestless", None, None)])
    entry = _vendor(consumer, "manifestless")
    assert_that(entry[SCAFFOLD_MARKER]).is_true()
    assert_that(entry["mapping"]).is_equal_to(
        {
            "skillRoots": ["skills"],
            "packages": [
                {
                    "id": "manifestless-skills",
                    "description": "Consumer-asserted mapping of skills.",
                    "skillsRoot": "skills",
                    "skills": "*",
                    "agents": ["helper"],
                }
            ],
        }
    )
    assert_that(entry["include"]).is_equal_to(["manifestless/manifestless-skills"])
    assert_that((consumer / "ai-skills.lock").exists()).is_false()
    locked, _, refusal = run_cli("lock", "--repo-root", str(consumer))
    assert_that(locked).is_equal_to(1)
    assert_that(refusal).contains(
        "mapping scaffold not accepted for vendor(s) manifestless"
    )
    _, report = validate_json(consumer)
    assert_that(codes(report, "schema")).contains("mapping.unaccepted")
    assert_that(_add(consumer, "fixture-org/manifestless")[0]).is_equal_to(1)
    status, output, error = _add(
        consumer, "fixture-org/manifestless", "--accept-mapping"
    )
    assert_that(status).described_as(error).is_zero()
    assert_that(output).contains("accepted consumer-asserted mapping")
    assert_that(_vendor(consumer, "manifestless")).does_not_contain_key(SCAFFOLD_MARKER)
    capabilities = _index(consumer)
    mapped = {
        key: value for key, value in capabilities.items() if "manifestless" in key
    }
    assert_that(sorted(mapped)).is_equal_to(
        [
            "manifestless/manifestless-skills:skill/delta",
            "manifestless/manifestless-skills:skill/epsilon",
            "manifestless/manifestless-skills:specialist/helper",
        ]
    )
    for record in mapped.values():
        assert_that(record["identity"]).is_equal_to("consumer-asserted")
        assert_that(record["lineage"][0]["lineage"][0]["publisher"]).is_equal_to(
            "manifestless"
        )
    assert_that(capabilities["consumer/local:skill/local"]).does_not_contain_key(
        "identity"
    )
    assert_that(_add(consumer, "fixture-org/manifestless")[0]).is_zero()


def test_unaccepted_scaffold_never_reaches_the_legacy_registry(
    consumer: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy-format consumer keeps its registry bytes until acceptance."""
    del forge
    from ai_skills_engine.manifest import legacy

    document = read_document(consumer / "ai-skills.yaml")
    document["x-legacy-format"] = {}
    (consumer / "ai-skills.yaml").write_text(dump_document(document))
    registry = {
        name: f"# {name} before add\n".encode() for name in ("vendors", "bundles")
    }
    for name, content in registry.items():
        (consumer / f"{name}.yaml").write_bytes(content)
    regenerated: list[Path] = []

    def write_legacy(root: Path, **_options: object) -> int:
        regenerated.append(root)
        (root / "vendors.yaml").write_text("# regenerated\n")
        return 0

    monkeypatch.setattr(legacy, "write_legacy", write_legacy)
    status, output, _ = _add(consumer, "fixture-org/manifestless")
    assert_that(status).is_equal_to(1)
    assert_that(output).contains("not locked")
    assert_that(_vendor(consumer, "manifestless")[SCAFFOLD_MARKER]).is_true()
    assert_that(regenerated).is_empty()
    for name, content in registry.items():
        assert_that((consumer / f"{name}.yaml").read_bytes()).is_equal_to(content)


def test_upstream_extensions_are_not_reported_as_vendor_authority(
    consumer: Path, forge: Forge
) -> None:
    """Upstream ``x-*`` keys are opaque extensions, not policy or overrides."""
    upstream = forge.trees["fixture-org/manifest"] / "ai-skills.yaml"
    document = read_document(upstream)
    document["x-notes"] = {"maintainer": "fixture"}
    upstream.write_text(dump_document(document))
    status, output, error = _add(consumer, "fixture-org/manifest")
    assert_that(status).described_as(error).is_zero()
    assert_that(output).contains(
        "add: ignored upstream x-notes: opaque upstream extension; not imported",
        "add: ignored upstream policy: vendor policy, trust grants and overrides",
    )
    assert_that(output).does_not_contain("x-notes: vendor policy")


def test_reexports_publish_only_exports_with_publisher_lineage(
    consumer: Path, forge: Forge
) -> None:
    """Importing alone never re-exports; exports gain each publisher's hop."""
    forge.pins["fixture-org/reexporter"] = PINS["fixture-org/reexporter"]
    status, _, error = _add(consumer, "fixture-org/reexporter", "--id", "hub")
    assert_that(status).described_as(error).is_zero()
    assert_that(_vendor(consumer, "hub")["include"]).is_equal_to(
        ["fixture-reexporter/tools", "fixture-vendor/core", "mapped/mapped-skills"]
    )
    lock = read_lock(consumer / "ai-skills.lock")
    assert_that([item.id for item in lock.vendors]).is_equal_to(
        ["hub", "hub/mapped", "hub/upstream"]
    )
    capabilities = _index(consumer)
    # The re-exporter imports fixture-vendor/crew but never exports it.
    assert_that([key for key in capabilities if "crew" in key]).is_empty()
    origins = [
        hop["origin"]
        for hop in capabilities["fixture-vendor/core:skill/alpha"]["lineage"][0][
            "lineage"
        ]
    ]
    assert_that(origins).is_equal_to(
        ["github.com/fixture-org/manifest", "github.com/fixture-org/reexporter"]
    )
    helper = capabilities["mapped/mapped-skills:specialist/helper"]
    assert_that(helper["identity"]).is_equal_to("consumer-asserted")
    document = read_document(consumer / "ai-skills.yaml")
    document["exports"] = ["local", "fixture-vendor/core"]
    (consumer / "ai-skills.yaml").write_text(dump_document(document))
    assert_that(run_cli("lock", "--repo-root", str(consumer))[0]).is_zero()
    capabilities = _index(consumer)
    exported = capabilities["fixture-vendor/core:skill/alpha"]["lineage"][0]["lineage"]
    imported = capabilities["fixture-reexporter/tools:skill/zeta"]["lineage"][0][
        "lineage"
    ]
    assert_that(exported[-1]["origin"]).is_equal_to("github.com/fixture-org/consumer")
    assert_that(exported[-1]["publisher"]).is_equal_to("consumer")
    assert_that([hop["publisher"] for hop in imported]).is_equal_to(
        ["fixture-reexporter"]
    )


def test_ambiguous_sha_and_branch_are_written_quoted(
    consumer: Path, forge: Forge
) -> None:
    """#568 parity: the writer quotes; the same values unquoted are rejected."""
    sha = "1e" + "1" * 38
    forge.pins["fixture-org/manifest"] = sha
    status, _, error = _add(consumer, "fixture-org/manifest", "--branch", "0o17")
    assert_that(status).described_as(error).is_zero()
    assert_that(forge.resolved).is_equal_to([("fixture-org/manifest", None, "0o17")])
    text = (consumer / "ai-skills.yaml").read_text()
    assert_that(text).contains(f'sha: "{sha}"', 'branch: "0o17"')
    assert_that(_vendor(consumer, "manifest")).contains_entry(
        {"sha": sha}, {"branch": "0o17"}
    )
    for plain in (text.replace(f'"{sha}"', sha), text.replace('"0o17"', "0o17")):
        (consumer / "ai-skills.yaml").write_text(plain)
        with pytest.raises(ValueError, match="quote the value"):
            read_document(consumer / "ai-skills.yaml")


def test_selectors_conflicts_and_failed_locks(
    consumer: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unoffered selectors and alias conflicts fail; a failed lock restores."""
    original = (consumer / "ai-skills.yaml").read_bytes()
    status, _, error = _add(
        consumer, "fixture-org/manifest", "--include", "fixture-vendor/extras"
    )
    assert_that(status).is_equal_to(1)
    assert_that(error).contains("fixture-vendor/extras is not offered")
    status, _, error = _add(consumer, "not a spec")
    assert_that(error).contains("expected OWNER/REPO[@REF]")
    with monkeypatch.context() as scoped:
        # Scoped: the forge's network and subprocess guards stay in force.
        scoped.setattr(add, "_lock", lambda root: 1)
        status, _, error = _add(consumer, "fixture-org/manifest")
    assert_that(status).is_equal_to(1)
    assert_that(error).contains("lock failed; ai-skills.yaml was restored")
    assert_that((consumer / "ai-skills.yaml").read_bytes()).is_equal_to(original)
    forge_status = _add(
        consumer,
        "fixture-org/manifest",
        "--include",
        "fixture-vendor/core:skill/alpha",
        "--exclude",
        "fixture-vendor/crew",
    )
    assert_that(forge_status[0]).described_as(forge_status[2]).is_zero()
    assert_that(_vendor(consumer, "manifest")).contains_entry(
        {"include": ["fixture-vendor/core:skill/alpha"]},
        {"exclude": ["fixture-vendor/crew"]},
    )
    status, _, error = _add(consumer, "fixture-org/manifestless", "--id", "manifest")
    assert_that(status).is_equal_to(1)
    assert_that(error).contains("already imports fixture-org/manifest")
    status, output, _ = _add(consumer, "fixture-org/manifest@main")
    assert_that(status).is_zero()
    assert_that(output).contains("already pins fixture-org/manifest@")


def test_add_never_executes_vendor_content(
    consumer: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Vendor hooks and scripts are copied as bytes only; nothing runs.

    The forge fixture already patches every subprocess entry point and
    ``os.system`` to fail; an executable vendor script would also leave a mark.
    """
    tree = forge.trees["fixture-org/manifestless"]
    marker = consumer.parent / "executed"
    script = tree / "skills/delta/install.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\n")
    script.chmod(0o755)
    (tree / "setup.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
    for name in ("execv", "execve", "execvp", "spawnv", "posix_spawn"):
        if hasattr(__import__("os"), name):
            monkeypatch.setattr(f"os.{name}", lambda *_a, **_k: pytest.fail("exec"))
    status, _, error = _add(consumer, "fixture-org/manifestless", "--accept-mapping")
    assert_that(status).described_as(error).is_zero()
    assert_that(marker.exists()).is_false()
    assert_that(re.search(r"\bsubprocess\b", error)).is_none()


def test_resolve_sha_skips_network_for_full_shas(forge: Forge) -> None:
    """Full SHAs are used as given; other refs go through the shared resolver."""
    sha = PINS["fixture-org/manifest"]
    assert_that(
        add.resolve_sha(repo="fixture-org/manifest", ref=sha, branch=None)
    ).is_equal_to(sha)
    assert_that(forge.resolved).is_empty()
    assert_that(
        add.resolve_sha(repo="fixture-org/manifest", ref="v1", branch="main")
    ).is_equal_to(sha)
    assert_that(forge.resolved).is_equal_to([("fixture-org/manifest", "v1", "main")])
