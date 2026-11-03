"""Build the actual wheel offline and exercise its installed-package boundary."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess  # nosec B404 - fixed local wheel build and isolated Python
import sys
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest
import yaml
from assertpy import assert_that

from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.migrate import vendor_declaration
from ai_skills_engine.registry.vendor import Vendor

pytest_plugins = ["ingest_helpers"]
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def wheel_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build and unpack exact wheel bytes in scratch without installing anything.

    Args:
        tmp_path_factory: Isolated build output directory factory.

    Returns:
        Pure Python installed-package layout outside every checkout.
    """
    scratch = tmp_path_factory.mktemp("ingest-wheel")
    uv_path = shutil.which("uv")
    if uv_path is None:
        pytest.fail("uv is required for the offline wheel proof")
    result = subprocess.run(  # nosec B603 - fixed local argv, offline, no shell
        [
            str(Path(uv_path).resolve()),
            "build",
            "--offline",
            "--wheel",
            "--out-dir",
            str(scratch),
            str(ROOT),
        ],
        cwd=scratch,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert_that(result.returncode).described_as(result.stdout + result.stderr).is_zero()
    wheel = next(scratch.glob("*.whl"))
    site = scratch / "site-packages"
    with ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.endswith("/"):
                continue
            target = site / name
            assert_that(target.resolve().is_relative_to(site.resolve())).is_true()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
            if name.startswith("ai_skills_engine/"):
                assert_that(target.read_bytes()).is_equal_to(
                    (ROOT / "src" / name).read_bytes()
                )
    assert_that(site.is_relative_to(ROOT)).is_false()
    return site


def probe(*, site: Path, root: Path, source: Path, operation: str) -> dict[str, Any]:
    """Launch wheel code with -I; source PYTHONPATH cannot influence imports.

    Args:
        site: Unpacked wheel package root.
        root: Synthetic author repository.
        source: Synthetic vendor snapshot.
        operation: Actual wheel command to run.

    Returns:
        Command result and verified installed import origins.
    """
    dependencies = Path(yaml.__file__).resolve().parent.parent
    result = subprocess.run(  # nosec B603 - fixed isolated interpreter argv, no shell
        [
            sys.executable,
            "-I",
            str(ROOT / "tests/fixtures/ingest/wheel_probe.py"),
            str(site),
            str(dependencies),
            str(root),
            str(source),
            operation,
        ],
        cwd=site.parent,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert_that(result.returncode).described_as(result.stdout + result.stderr).is_zero()
    report: dict[str, Any] = json.loads(result.stdout)
    for field in ("module", "schema"):
        assert_that(Path(report[field]).is_relative_to(site)).is_true()
    return report


def test_wheel_bakes_checks_and_rejects_forged_lock(
    wheel_site: Path, ingest_repo: tuple[Path, Path, Vendor]
) -> None:
    """Real wheel bytes enforce public APIs, no execution and offline rescans."""
    root, source, _vendor = ingest_repo
    (source / "skills/helper/setup.py").write_text(
        "raise RuntimeError('MUST NOT EXECUTE')\n"
    )
    assert_that(
        probe(site=wheel_site, root=root, source=source, operation="bake")["status"]
    ).is_zero()
    assert_that(
        probe(site=wheel_site, root=root, source=source, operation="check")["status"]
    ).is_zero()
    baked = root / "plugins-baked"
    # Repeated characters make this a clearly synthetic provider shape.
    sample = b"AKIA" + b"A" * 16
    target = baked / "synthetic-plugin/skills/helper/synthetic.txt"
    target.write_bytes(sample)
    target.chmod(0o644)
    lock_path = baked / "BAKE.json"
    lock = json.loads(lock_path.read_text())
    lock["files"][target.relative_to(baked).as_posix()] = hashlib.sha256(
        sample
    ).hexdigest()
    lock["ingestChecks"] = {"acknowledgedFindings": [], "ruleSetVersion": "forged"}
    lock_path.write_text(json.dumps(lock))
    report = probe(site=wheel_site, root=root, source=source, operation="check")
    assert_that(report["status"]).is_equal_to(1)
    assert_that(report["stderr"]).contains("aws-access-key-id").does_not_contain(
        sample.decode()
    )


def test_wheel_manifest_policy_reaches_legacy_reader(
    wheel_site: Path, ingest_repo: tuple[Path, Path, Vendor]
) -> None:
    """The packaged schema, typed model and actual legacy CLI preserve policy."""
    root, source, _vendor = ingest_repo
    raw = yaml.safe_load((root / "vendors.yaml").read_text())["vendors"][0]
    raw["ingestAllow"] = [
        {
            "path": "skills/helper/example.txt",
            "rule": "aws-access-key-id",
            "sha256": "a" * 64,
            "reason": "Synthetic documentation example",
        }
    ]
    raw["ingestLimits"] = {
        "fileBytes": 6 * 1024 * 1024,
        "reason": "Synthetic reviewed override",
    }
    document = {
        "apiVersion": "ai-skills.dev/v1",
        "publisher": {"id": "synthetic"},
        "vendors": [vendor_declaration(raw)],
        "exports": ["synthetic-vendor/synthetic-plugin"],
    }
    (root / "skills").mkdir()
    (root / "ai-skills.yaml").write_text(dump_document(document))
    report = probe(site=wheel_site, root=root, source=source, operation="legacy")
    assert_that(report["status"]).described_as(report).is_zero()
    projected = yaml.safe_load((root / "vendors.yaml").read_text())["vendors"][0]
    for field in ("ingestAllow", "ingestLimits"):
        assert_that(projected[field]).is_equal_to(raw[field])


def test_wheel_pem_acknowledgement_privacy(
    wheel_site: Path,
    ingest_repo: tuple[Path, Path, Vendor],
    pem_acknowledgement: str,
) -> None:
    """Actual wheel bake/check outputs apply the same PEM privacy contract."""
    root, source, vendor = ingest_repo
    baked_result = probe(site=wheel_site, root=root, source=source, operation="bake")
    checked_result = probe(site=wheel_site, root=root, source=source, operation="check")
    assert_that(baked_result["status"]).is_zero()
    assert_that(checked_result["status"]).is_zero()
    baked = root / "plugins-baked"
    lock = json.loads((baked / "BAKE.json").read_text())
    findings = lock["ingestChecks"]["vendors"][vendor.id]["acknowledgedFindings"]
    assert_that(findings).is_length(1)
    assert_that(findings[0]["reason"]).is_equal_to(pem_acknowledgement)
    report = (baked / "COVERAGE.md").read_text()
    assert_that(report).contains(pem_acknowledgement)
    assert_that(baked_result["stdout"]).contains(pem_acknowledgement)
    for result in (baked_result, checked_result):
        assert_that(result["stderr"]).is_empty()
    for output in (
        json.dumps(lock),
        report,
        json.dumps(baked_result),
        json.dumps(checked_result),
    ):
        assert_that(output).does_not_contain(
            "SYNTHETIC_PRIVATE_BODY_CONTROL_572", "-----BEGIN", "-----END"
        )
