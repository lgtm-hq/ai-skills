"""``validate`` runs every stage in order and fails on any stage's error."""

import json
import os
import shutil
import subprocess  # nosec B404 - trusted local wheel commands, no shell
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from assertpy import assert_that
from authoring_helpers import FIXTURES, codes, run_cli, stage, validate_json

from ai_skills_engine.commands.validate_report import STAGES
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.registry.vendor import Vendor
from ai_skills_engine.source_cache import SourceCache, canonical_snapshot

pytest_plugins = ["authoring_helpers", "test_ingest_wheel"]


@pytest.fixture
def vendor(tmp_path: Path) -> Path:
    """Copy the manifest fixture vendor as a repository under validation.

    Args:
        tmp_path: Test directory.

    Returns:
        Repository root.
    """
    root = tmp_path / "vendor"
    shutil.copytree(FIXTURES / "manifest", root)
    return root


def _edit(root: Path, change: Callable[[dict[str, Any]], None]) -> None:
    """Rewrite the manifest after applying a change.

    Args:
        root: Repository root.
        change: In-place document edit.
    """
    document = read_document(root / "ai-skills.yaml")
    change(document)
    (root / "ai-skills.yaml").write_text(dump_document(document))


def test_fixture_vendor_passes_every_stage_in_order(vendor: Path) -> None:
    """Text and JSON outputs list the issue's ten stages in order."""
    status, report = validate_json(vendor, "--strict")
    assert_that(status).is_zero()
    assert_that(report["ok"]).is_true()
    assert_that(report["strict"]).is_true()
    assert_that([item["name"] for item in report["stages"]]).is_equal_to(
        [name for name, _ in STAGES]
    )
    assert_that([item["status"] for item in report["stages"]]).is_equal_to(
        ["passed"] * 8 + ["skipped", "skipped"]
    )
    text_status, text, _ = run_cli("validate", "--repo-root", str(vendor))
    assert_that(text_status).is_zero()
    assert_that(text).contains(
        "[1/10] schema and terminology lint: passed",
        "[10/10] generate --check: skipped (no committed host marketplaces)",
        "validate: passed",
    )


def test_reexporter_reports_and_never_applies_vendor_policy(tmp_path: Path) -> None:
    """The upstream's deny of the re-exporter is reported as ignored."""
    root = tmp_path / "reexporter"
    shutil.copytree(FIXTURES / "reexporter", root)
    status, report = validate_json(
        root,
        "--strict",
        "--vendor-root",
        f"upstream={FIXTURES / 'manifest'}",
        "--vendor-root",
        f"mapped={FIXTURES / 'manifestless'}",
    )
    assert_that(status).described_as(json.dumps(report, indent=1)).is_zero()
    assert_that(report["ignored"]).is_length(1)
    assert_that(report["ignored"][0]).contains_entry(
        {"code": "vendor-authority-ignored"}, {"location": "/vendors/upstream/policy"}
    )
    assert_that(report["ignored"][0]["message"]).contains("never applied")
    _, unavailable = validate_json(root)
    assert_that(codes(unavailable, "inventory")).contains(
        "validate.vendor-source-unavailable"
    )
    assert_that(codes(unavailable, "exports")).is_equal_to(["export.unverifiable"])


def test_schema_and_terminology_failures_block_later_stages(vendor: Path) -> None:
    """Structural errors fail stage 1 and skip the dependent stages."""
    _edit(vendor, lambda document: document.update({"unknown": True}))
    status, report = validate_json(vendor)
    assert_that(status).is_equal_to(1)
    assert_that(stage(report, "schema")["status"]).is_equal_to("failed")
    assert_that({item["status"] for item in report["stages"][1:]}).is_equal_to(
        {"skipped"}
    )
    _edit(vendor, lambda document: document.pop("unknown"))
    _edit(
        vendor,
        lambda document: document["packages"][0].update(
            {"description": "A bundle of fixture skills."}
        ),
    )
    status, report = validate_json(vendor)
    assert_that(status).is_equal_to(1)
    assert_that(stage(report, "schema")["status"]).is_equal_to("failed")
    missing, _, _ = run_cli("validate", "--repo-root", str(vendor.parent / "none"))
    assert_that(missing).is_equal_to(1)


def test_vendor_glossary_is_never_held_to_this_catalog_by_default(
    vendor: Path,
) -> None:
    """A vendor's own docs glossary passes; ``--terminology`` opts into ours."""
    (vendor / "docs").mkdir()
    (vendor / "docs/glossary.md").write_text(
        "# Glossary\n\n## widget\n\nA vendor-specific term.\n"
    )
    (vendor / "docs/usage.md").write_text("# Usage\n\nInstall the bundle first.\n")
    status, report = validate_json(vendor, "--strict")
    assert_that(status).described_as(json.dumps(report, indent=1)).is_zero()
    assert_that(stage(report, "schema")["status"]).is_equal_to("passed")
    status, report = validate_json(vendor, "--strict", "--terminology")
    assert_that(status).is_equal_to(1)
    assert_that(stage(report, "schema")["status"]).is_equal_to("failed")
    assert_that(set(codes(report, "schema"))).is_equal_to(
        {"glossary-term-missing", "terminology"}
    )
    assert_that(
        [item["location"] for item in stage(report, "schema")["diagnostics"]]
    ).contains("docs/glossary.md", "docs/usage.md")
    assert_that({item["status"] for item in report["stages"][1:]}).is_equal_to(
        {"skipped"}
    )
    # Manifest descriptions are linted for everyone, with or without the flag.
    _edit(
        vendor,
        lambda document: document["packages"][0].update(
            {"description": "A component of fixture skills."}
        ),
    )
    status, report = validate_json(vendor)
    assert_that(status).is_equal_to(1)
    assert_that(codes(report, "schema")).is_equal_to(["terminology"])


def test_this_catalog_passes_the_opt_in_docs_glossary_stage() -> None:
    """ai-skills itself, which CI validates with ``terminology``, passes stage 1."""
    from ai_skills_engine.commands import validate
    from ai_skills_engine.commands.validate_report import Report

    root = Path(__file__).resolve().parents[1]
    report = Report(strict=True)
    loaded = validate._schema(  # pylint: disable=protected-access
        root=root, report=report, roots={}, terminology=True
    )
    assert_that(loaded).is_not_none()
    assert_that(report.stages["schema"].findings).is_empty()


def test_inventory_selection_and_collision_failures(vendor: Path) -> None:
    """Inventory payload errors, unmatched selectors and name collisions fail."""
    (vendor / "skills/beta/SKILL.md").write_text("no frontmatter\n")
    _, report = validate_json(vendor)
    assert_that(stage(report, "inventory")["status"]).is_equal_to("failed")
    shutil.copytree(
        FIXTURES / "manifest/skills/beta", vendor / "skills/beta", dirs_exist_ok=True
    )

    def unmatched(document: dict[str, Any]) -> None:
        document["packages"][0]["include"] = ["fixture-vendor/core:skill/missing"]

    _edit(vendor, unmatched)
    _, report = validate_json(vendor)
    assert_that(stage(report, "selection")["status"]).is_equal_to("failed")
    assert_that(codes(report, "selection")).contains("selection.selector-unmatched")
    _edit(vendor, lambda document: document["packages"][0].pop("include"))
    shutil.copytree(vendor / "skills/alpha", vendor / "skills/alpha-copy")

    def collide(document: dict[str, Any]) -> None:
        document["packages"][1]["capabilities"].append(
            {"id": "alpha", "path": "skills/alpha-copy"}
        )

    _edit(vendor, collide)
    status, report = validate_json(vendor)
    assert_that(status).is_equal_to(1)
    assert_that(stage(report, "collisions")["status"]).is_equal_to("failed")
    assert_that(codes(report, "collisions")).contains(
        "selection.namespace-collision", "collision.shared-name"
    )


def test_strict_turns_missing_lineage_into_failure(
    vendor: Path, tmp_path: Path
) -> None:
    """Byte equality with a declared pin lacking lineage fails only when strict."""
    consumer = tmp_path / "copier"
    (consumer / "skills").mkdir(parents=True)
    shutil.copytree(vendor / "skills/alpha", consumer / "skills/alpha")
    (consumer / "ai-skills.yaml").write_text(
        dump_document(
            {
                "apiVersion": "ai-skills.dev/v1",
                "publisher": {"id": "copier", "repo": "fixture-org/copier"},
                "packages": [
                    {
                        "id": "own",
                        "capabilities": [{"id": "alpha", "path": "skills/alpha"}],
                    }
                ],
                "vendors": [
                    {
                        "id": "upstream",
                        "repo": "fixture-org/manifest",
                        "sha": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
                        "include": [],
                    }
                ],
                "exports": ["own"],
            }
        )
    )
    roots = ("--vendor-root", f"upstream={vendor}")
    status, report = validate_json(consumer, *roots)
    assert_that(status).described_as(json.dumps(report, indent=1)).is_zero()
    assert_that(stage(report, "provenance")["diagnostics"][0]).contains_entry(
        {"severity": "warning"}, {"code": "provenance.missing-lineage"}
    )
    status, report = validate_json(consumer, "--strict", *roots)
    assert_that(status).is_equal_to(1)
    assert_that(stage(report, "provenance")["status"]).is_equal_to("failed")


def test_own_content_ingest_and_link_failures(vendor: Path) -> None:
    """Secret shapes and escaping links in own content fail stages 5 and 6."""
    token = "ghp_" + "A1b2C3d4E5" * 3 + "F6g7H8"
    (vendor / "skills/alpha/notes.md").write_text(f"token {token}\n")
    (vendor / "skills/beta/SKILL.md").write_text(
        (vendor / "skills/beta/SKILL.md").read_text()
        + "\nSee [alpha](../alpha/SKILL.md).\n"
    )
    status, report = validate_json(vendor)
    assert_that(status).is_equal_to(1)
    assert_that(codes(report, "ingest")).is_equal_to(["ingest.rejected"])
    assert_that(stage(report, "ingest")["diagnostics"][0]["message"]).contains(
        "unacknowledged secret shape"
    ).does_not_contain(token)
    assert_that(stage(report, "links")["diagnostics"][0]).contains_entry(
        {"code": "links.internal-reference"},
        {"location": "fixture-vendor/core:skill/beta"},
    )


def test_dead_and_non_imported_exports_fail(vendor: Path) -> None:
    """Exports matching nothing, or content that is not imported, fail stage 8."""

    def empty(document: dict[str, Any]) -> None:
        document["packages"].append({"id": "empty"})
        document["exports"] = ["core", "crew", "empty", "fixture-vendor/missing"]

    _edit(vendor, empty)
    _, report = validate_json(vendor)
    assert_that(stage(report, "exports")["diagnostics"]).is_equal_to(
        [
            {
                "severity": "error",
                "code": "export.not-imported",
                "location": "/exports/3",
                "message": "Export is not a local or imported package: "
                "fixture-vendor/missing",
            },
            {
                "severity": "error",
                "code": "export.matches-nothing",
                "location": "/exports/2",
                "message": "Export empty matches no capability or resource",
            },
        ]
    )

    def excluded(document: dict[str, Any]) -> None:
        document["packages"].pop()
        document["packages"][2]["exclude"] = ["fixture-vendor/crew:specialist/reviewer"]
        document["exports"] = ["core", "crew"]

    _edit(vendor, excluded)
    _, report = validate_json(vendor)
    assert_that(codes(report, "exports")).is_equal_to(["export.not-imported"])


def test_export_of_rejected_content_names_inventory_rejection(vendor: Path) -> None:
    """An export whose only match failed inventory checks is not called excluded."""
    from dataclasses import replace

    from ai_skills_engine.commands import validate_checks
    from ai_skills_engine.manifest.load import load_consumer
    from ai_skills_engine.selection.load import load_inputs

    inventory, selection = load_inputs(vendor, vendor_roots=None)
    consumer, _, _ = load_consumer(vendor / "ai-skills.yaml", vendor_roots={})
    reviewer = next(
        item for item in inventory.capabilities if str(item.id).endswith("/reviewer")
    )
    inventory = replace(
        inventory,
        capabilities=tuple(
            item for item in inventory.capabilities if item.id != reviewer.id
        ),
        rejected=(*inventory.rejected, reviewer.id),
    )
    selection = replace(
        selection,
        capabilities=tuple(
            item for item in selection.capabilities if item.id != str(reviewer.id)
        ),
    )
    findings = validate_checks.exports(
        consumer=consumer,
        inventory=inventory,
        selection=selection,
        roots={},
        dangling=(),
    )
    assert_that([(item.code, item.location) for item in findings]).is_equal_to(
        [("export.not-imported", "/exports/1")]
    )
    assert_that(findings[0].message).contains(
        "Export crew names content that is not imported",
        "rejected by inventory checks",
    ).does_not_contain("include/exclude")


def test_lock_and_generate_checks_run_the_real_commands(vendor: Path) -> None:
    """A stale lock and stale marketplaces fail stages 9 and 10."""
    # Repo-root marketplaces carry skill slices only; specialists need envelopes.
    _edit(vendor, lambda document: document.update({"exports": ["core"]}))
    assert_that(run_cli("lock", "--repo-root", str(vendor))[0]).is_zero()
    assert_that(run_cli("generate", "--repo-root", str(vendor))[0]).is_zero()
    status, report = validate_json(vendor, "--strict")
    assert_that(status).described_as(json.dumps(report, indent=1)).is_zero()
    assert_that([item["status"] for item in report["stages"][-2:]]).is_equal_to(
        ["passed", "passed"]
    )
    (vendor / "skills/alpha/SKILL.md").write_text(
        (vendor / "skills/alpha/SKILL.md").read_text() + "\nChanged.\n"
    )
    (vendor / ".claude-plugin/marketplace.json").write_text("{}\n")
    status, report = validate_json(vendor)
    assert_that(status).is_equal_to(1)
    assert_that(stage(report, "lock")["diagnostics"][0]["message"]).contains(
        "ai-skills.lock is stale"
    )
    assert_that(stage(report, "generate")["diagnostics"][0]["message"]).contains(
        ".claude-plugin/marketplace.json is out of date"
    )


def test_validate_uses_only_the_source_cache_and_never_executes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cached pins become vendor inputs offline; subprocess is never invoked."""
    root = tmp_path / "reexporter"
    shutil.copytree(FIXTURES / "reexporter", root)
    for name, repo, sha in (
        (
            "manifest",
            "fixture-org/manifest",
            "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
        ),
        (
            "manifestless",
            "fixture-org/manifestless",
            "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c",
        ),
    ):
        pin = Vendor(
            id=name, repo=repo, sha=sha, skill_roots=(), license="", homepage=""
        )
        SourceCache.default().store(
            data=canonical_snapshot(tree=FIXTURES / name, vendor=pin),
            repo=repo,
            revision=sha,
            label=name,
            expected=None,
        )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("validate must not run subprocesses or use the network")

    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    status, report = validate_json(root, "--strict")
    assert_that(status).described_as(json.dumps(report, indent=1)).is_zero()
    assert_that(codes(report, "inventory")).does_not_contain(
        "validate.vendor-source-unavailable"
    )


def test_actual_wheel_runs_init_validate_and_add_outside_checkout(
    wheel_site: Path, tmp_path: Path
) -> None:
    """Shipped resources drive the public commands from an unrelated directory."""
    dependencies = Path(yaml.__file__).resolve().parent.parent
    launcher = tmp_path / "ai-skills-engine"
    launcher.write_text(
        f"#!{sys.executable} -I\n"
        "import sys\n"
        f"sys.path[:0] = {[str(wheel_site), str(dependencies)]!r}\n"
        "from importlib.metadata import Distribution\n"
        "distribution = Distribution.at(\n"
        f"    {str(next(wheel_site.glob('*.dist-info')))!r}\n)\n"
        "entry = next(item for item in distribution.entry_points\n"
        "    if item.group == 'console_scripts'\n"
        "    and item.name == 'ai-skills-engine')\n"
        "import ai_skills_engine.commands.validate as validate\n"
        "from pathlib import Path\n"
        f"assert Path(validate.__file__).is_relative_to(Path({str(wheel_site)!r}))\n"
        "raise SystemExit(entry.load()())\n"
    )
    launcher.chmod(0o755)
    cache = tmp_path / "cache"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {"PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONHOME"}
    } | {"AI_SKILLS_CACHE": str(cache)}
    sha = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c"
    pin = Vendor(
        id="tools",
        repo="fixture-org/manifestless",
        sha=sha,
        skill_roots=(),
        license="",
        homepage="",
    )
    SourceCache(root=cache).store(
        data=canonical_snapshot(tree=FIXTURES / "manifestless", vendor=pin),
        repo=pin.repo,
        revision=sha,
        label="tools",
        expected=None,
    )
    root = tmp_path / "publisher"
    shutil.copytree(
        FIXTURES / "manifest", root, ignore=shutil.ignore_patterns("ai-skills.yaml")
    )

    def run(*arguments: str) -> subprocess.CompletedProcess[str]:
        """Run the wheel entry point from outside every checkout.

        Args:
            arguments: Command line.

        Returns:
            Completed process.
        """
        return subprocess.run(  # nosec B603 - explicit local wheel entrypoint
            args=[str(launcher), *arguments],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )

    for arguments in (
        ("init", "--engine-ref", "ab" * 20, "--publisher", "wheel-vendor"),
        ("validate", "--strict", "--format", "json"),
        ("add", f"fixture-org/manifestless@{sha}", "--id", "tools", "--accept-mapping"),
        ("validate", "--strict"),
    ):
        result = run(*arguments)
        assert_that(result.returncode).described_as(
            result.stdout + result.stderr
        ).is_zero()
    assert_that(json.loads(run("validate", "--format", "json").stdout)["ok"]).is_true()
    assert_that((root / "ai-skills.lock").is_file()).is_true()
    assert_that(Path(__file__).resolve().parents[1].is_relative_to(root)).is_false()


def test_unreadable_source_cache_is_reported_not_swallowed(
    vendor: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source-cache failure becomes a visible warning on a valid manifest."""
    from ai_skills_engine.commands import validate_checks

    def unreadable(**_kwargs: object) -> object:
        """Fail like an unreadable cache root."""
        raise PermissionError("cache root is not readable")

    monkeypatch.setattr(validate_checks, "cached_sources", unreadable)
    _status, report = validate_json(vendor)
    findings = stage(report, "inventory")["diagnostics"]
    assert_that(
        [
            (item["code"], item["location"])
            for item in findings
            if "cache root is not readable" in item["message"]
        ]
    ).is_equal_to([("validate.vendor-source-unavailable", "/vendors")])
