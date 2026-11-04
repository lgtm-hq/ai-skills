"""Build the actual wheel offline and exercise its installed-package boundary."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess  # nosec B404 - fixed local wheel build and isolated Python
import sys
import tarfile
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest
import yaml
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.manifest.migrate import vendor_declaration
from ai_skills_engine.registry.vendor import Vendor

pytest_plugins = ["ingest_helpers", "inventory_helpers"]
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


@pytest.mark.parametrize("control", ["clean", "secret", "acknowledged", "stale"])
def test_wheel_selection_candidates_retain_ingestion_policy(
    wheel_site: Path,
    inventory_repo: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    control: str,
) -> None:
    """Dependency closure retains consumer policy in both source and actual wheel."""
    from inventory_helpers import inventory_snapshot

    root, vendor = inventory_repo
    sample = b"AKIA" + b"A" * 16
    payload = vendor / "skills/help/synthetic.txt"
    payload.write_bytes(b"Synthetic example\n" + sample)
    document = read_document(root / "ai-skills.yaml")
    # This vendor is needed only by closure, despite the empty direct include.
    document["vendors"][0]["include"] = []
    if control == "clean":
        payload.write_bytes(b"ordinary payload\n")
    elif control in {"acknowledged", "stale"}:
        document["vendors"][0]["ingestAllow"] = [
            {
                "path": "skills/help/synthetic.txt",
                "rule": "aws-access-key-id",
                "sha256": (
                    hashlib.sha256(payload.read_bytes()).hexdigest()
                    if control == "acknowledged"
                    else "0" * 64
                ),
                "reason": "Synthetic documentation acknowledgement",
            }
        ]
    (root / "ai-skills.yaml").write_text(dump_document(document))
    before = inventory_snapshot(root, vendor)
    expected = int(control in {"secret", "stale"})
    assert_that(
        cli.main(
            [
                "plan",
                "--repo-root",
                str(root),
                "--vendor-root",
                f"vendor={vendor}",
                "--json",
            ]
        )
    ).is_equal_to(expected)
    source = capsys.readouterr()
    report = probe(site=wheel_site, root=root, source=vendor, operation="plan")
    assert_that(report["status"]).is_equal_to(expected)
    assert_that((report["stdout"], report["stderr"])).is_equal_to(
        (source.out, source.err)
    )
    assert_that(source.out + source.err).does_not_contain(sample.decode())
    if expected:
        assert_that(source.out + source.err).contains("aws-access-key-id")
    else:
        helper = next(
            item
            for item in json.loads(source.out)["capabilities"]
            if item["id"] == "vendor/tools:skill/helper"
        )
        assert_that(helper["state"]).is_equal_to("pulled-in")
    assert_that(inventory_snapshot(root, vendor)).is_equal_to(before)


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


def test_wheel_root_layout_preflight_preserves_rejected_destination(
    wheel_site: Path,
    tmp_path: Path,
    root_archive: tuple[bytes, str | None],
    archive_destination: Path,
) -> None:
    """Isolated built-wheel extraction retains one root and rejects invalid ones."""
    payload, error = root_archive
    archive_path = tmp_path / "input.tar.gz"
    archive_path.write_bytes(payload)
    destination = archive_destination
    existed = destination.exists()
    inode = destination.stat().st_ino if existed else None
    sentinel_inode = (destination / "sentinel").stat().st_ino if existed else None
    result = probe(
        site=wheel_site, root=destination, source=archive_path, operation="extract"
    )
    assert_that(result["stdout"]).is_empty()
    if error is None:
        assert_that(result["status"]).described_as(result).is_zero()
        assert_that(result["stderr"]).is_empty()
        assert_that(sorted(path.name for path in destination.iterdir())).is_equal_to(
            ["asset.txt", "other.txt"]
        )
        asset = destination / "asset.txt"
        assert_that(asset.read_bytes()).is_equal_to(b"actual fixture payload\n")
        assert_that(asset.stat().st_mode & 0o7777).is_equal_to(0o644)
        other = destination / "other.txt"
        assert_that(other.read_bytes()).is_equal_to(b"second fixture payload\n")
        assert_that(other.stat().st_mode & 0o7777).is_equal_to(0o644)
        return
    assert_that(result["status"]).is_equal_to(1)
    assert_that(result["stderr"]).contains(
        "synthetic-vendor", error, "directory"
    ).does_not_contain("AKIA" + "A" * 16)
    if error == "top-level":
        assert_that(result["stderr"]).contains("loose")
    if ("AKIA" + "A" * 16).encode() in payload:
        assert_that(result["stderr"]).contains("[REDACTED]")
    if existed:
        sentinel = destination / "sentinel"
        assert_that(list(destination.iterdir())).is_equal_to([sentinel])
        assert_that(sentinel.read_bytes()).is_equal_to(b"\x00original sentinel\xff\n")
        assert_that(sentinel.stat().st_mode & 0o7777).is_equal_to(0o640)
        assert_that(sentinel.stat().st_ino).is_equal_to(sentinel_inode)
        assert_that(destination.stat().st_mode & 0o7777).is_equal_to(0o750)
        assert_that(destination.stat().st_ino).is_equal_to(inode)
        assert_that(list(destination.parent.iterdir())).is_equal_to([destination])
    else:
        assert_that(destination.parent.exists()).is_false()


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


@pytest.mark.parametrize("control", ["clean", "both-excluded", "retained", "required"])
def test_wheel_plan_recovers_independent_declarations(
    wheel_site: Path,
    rejected_inventory: tuple[Path, Path, str, str],
    capsys: pytest.CaptureFixture[str],
    control: str,
) -> None:
    """Actual wheel selection retains valid declarations and typed failure evidence."""
    from test_ingest_inventory import configure_selection

    root, source, bad, requirer = rejected_inventory
    if control == "clean":
        (source / "bad.md").write_text("Ordinary independent Markdown\n")
    configure_selection(root=root, bad=bad, requirer=requirer, control=control)
    expected = int(control not in {"clean", "both-excluded"})
    assert_that(
        cli.main(
            [
                "plan",
                "--repo-root",
                str(root),
                "--vendor-root",
                f"vendor={source}",
                "--json",
            ]
        )
    ).is_equal_to(expected)
    output = capsys.readouterr()
    result = probe(site=wheel_site, root=root, source=source, operation="plan")
    assert_that(result["status"]).is_equal_to(expected)
    assert_that((result["stdout"], result["stderr"])).is_equal_to(
        (output.out, output.err)
    )
    assert_that(json.dumps(result)).does_not_contain("AKIA" + "A" * 16)
    document = json.loads(result["stdout"])
    assert_that([item["id"] for item in document["capabilities"]]).contains(
        "upstream/tools:skill/good", requirer
    )


@pytest.mark.parametrize("kind", ["small", "coverage", "lock"])
@pytest.mark.parametrize("existing", [False, True], ids=["absent", "existing"])
def test_wheel_metadata_publication_contract(
    wheel_site: Path,
    ingest_repo: tuple[Path, Path, Vendor],
    kind: str,
    existing: bool,
) -> None:
    """Real wheel generation rejects oversized metadata before publication."""
    from ingest_helpers import configure_metadata_reason
    from inventory_helpers import inventory_snapshot

    root, source, _ = ingest_repo
    output = root / "plugins-baked"
    if existing:
        assert_that(
            probe(site=wheel_site, root=root, source=source, operation="bake")["status"]
        ).is_zero()
        output.chmod(0o750)
        (output / "COVERAGE.md").chmod(0o640)
    before = inventory_snapshot(output) if existing else {}
    configure_metadata_reason(root=root, source=source, kind=kind)
    result = probe(site=wheel_site, root=root, source=source, operation="bake-cli")
    assert_that(result["status"]).is_equal_to(0 if kind == "small" else 1)
    if kind == "small":
        assert_that(
            probe(site=wheel_site, root=root, source=source, operation="check")[
                "status"
            ]
        ).is_zero()
    else:
        assert_that(result["stderr"]).contains(
            "fileBytes", "COVERAGE.md" if kind == "coverage" else "BAKE.json"
        )
        if existing:
            assert_that(inventory_snapshot(output)).is_equal_to(before)
        else:
            assert_that(output.exists()).is_false()


def test_wheel_google_acknowledgement_privacy(
    wheel_site: Path,
    ingest_repo: tuple[Path, Path, Vendor],
    google_acknowledgement: str,
) -> None:
    """The installed wheel detects and redacts the same trailing-hyphen shape."""
    root, source, vendor = ingest_repo
    result = probe(site=wheel_site, root=root, source=source, operation="bake-cli")
    assert_that(result["status"]).is_zero()
    checked = probe(site=wheel_site, root=root, source=source, operation="check")
    assert_that(checked["status"]).is_zero()
    baked = root / "plugins-baked"
    lock = (baked / "BAKE.json").read_text()
    findings = json.loads(lock)["ingestChecks"]["vendors"][vendor.id][
        "acknowledgedFindings"
    ]
    assert_that(findings).is_length(1)
    assert_that(findings[0]["reason"]).is_equal_to("Synthetic example [REDACTED]")
    for text in (
        json.dumps(result),
        json.dumps(checked),
        lock,
        (baked / "COVERAGE.md").read_text(),
    ):
        assert_that(text).does_not_contain(google_acknowledgement)
    target = baked / "synthetic-plugin/skills/helper/example.txt"
    target.write_bytes(target.read_bytes() + b"changed")
    failed = probe(site=wheel_site, root=root, source=source, operation="check")
    assert_that(failed["status"]).is_equal_to(1)
    assert_that(failed["stderr"]).contains(
        "google-api-key", "unacknowledged"
    ).does_not_contain(google_acknowledgement)
    # The real bake CLI must also fail without the consumer acknowledgement.
    policy_path = root / "vendors.yaml"
    policy = yaml.safe_load(policy_path.read_text())
    policy["vendors"][0].pop("ingestAllow")
    policy_path.write_text(yaml.safe_dump(policy))
    before = {path: path.read_bytes() for path in baked.rglob("*") if path.is_file()}
    rejected = probe(site=wheel_site, root=root, source=source, operation="bake-cli")
    assert_that(rejected["status"]).is_equal_to(1)
    assert_that(rejected["stderr"]).contains("google-api-key").does_not_contain(
        google_acknowledgement
    )
    assert_that({path: path.read_bytes() for path in before}).is_equal_to(before)


@pytest.mark.parametrize(
    "target", ["asset", "../root/asset", "../outside", "/root/asset"]
)
def test_wheel_symlink_target_coordinates(
    wheel_site: Path,
    archive_destination: Path,
    tmp_path: Path,
    target: str,
) -> None:
    """Installed extraction translates re-entering links without accepting escapes."""
    from inventory_helpers import inventory_snapshot

    destination = archive_destination
    existed = destination.exists()
    before = inventory_snapshot(destination) if existed else {}
    payload = io.BytesIO()
    data = b"ordinary fixture payload\n"
    with tarfile.open(fileobj=payload, mode="w:gz", compresslevel=0) as archive:
        asset = tarfile.TarInfo("root/asset")
        asset.size = len(data)
        archive.addfile(asset, io.BytesIO(data))
        link = tarfile.TarInfo("root/link")
        link.type = tarfile.SYMTYPE
        link.linkname = target
        archive.addfile(link)
    source = tmp_path / "input.tar.gz"
    source.write_bytes(payload.getvalue())
    result = probe(
        site=wheel_site, root=destination, source=source, operation="extract"
    )
    accepted = target in {"asset", "../root/asset"}
    assert_that(result["status"]).is_equal_to(0 if accepted else 1)
    if accepted:
        assert_that((destination / "link").is_symlink()).is_true()
        assert_that((destination / "link").read_bytes()).is_equal_to(data)
        assert_that((destination / "asset").stat().st_mode & 0o7777).is_equal_to(0o644)
    elif existed:
        assert_that(inventory_snapshot(destination)).is_equal_to(before)
    else:
        assert_that(destination.exists()).is_false()
