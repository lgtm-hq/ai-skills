"""Ingest selected bytes safely, including offline checks and public APIs."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess  # nosec B404 - patched to prohibit vendor execution
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml
from assertpy import assert_that

from ai_skills_engine.bake import vendor_plugins as baker
from ai_skills_engine.registry.ingest_allow import IngestAllow
from ai_skills_engine.registry.ingest_checks import (
    inspect_bytes,
    parse_allow,
    parse_limits,
    read_bounded,
    scan_paths,
)
from ai_skills_engine.registry.ingest_limits import IngestLimits
from ai_skills_engine.registry.plugin_bake import bake_vendor_plugins
from ai_skills_engine.registry.vendor import Vendor

pytest_plugins = ["ingest_helpers"]

# Every shape below is synthetic, generated from repeated characters; no credential.
SYNTHETIC_SHAPES = [
    ("pem-private-key", b"-" * 5 + b"BEGIN PRIVATE KEY" + b"-" * 5),
    ("pem-private-key", b"-" * 5 + b"BEGIN RSA PRIVATE KEY" + b"-" * 5),
    ("pem-private-key", b"-" * 5 + b"BEGIN OPENSSH PRIVATE KEY" + b"-" * 5),
    ("aws-access-key-id", b"AKIA" + b"A" * 16),
    *(("github-token", f"gh{kind}_".encode() + b"A" * 36) for kind in "pousr"),
    ("github-token", b"github_pat_" + b"A" * 22),
    *(("slack-token", f"xox{kind}-".encode() + b"A" * 20) for kind in "abprs"),
    ("google-api-key", b"AIza" + b"A" * 35),
    ("npm-token", b"npm_" + b"A" * 36),
    ("stripe-live-key", b"sk_live_" + b"A" * 24),
    ("anthropic-api-key", b"sk-ant-" + b"A" * 24),
    ("openai-project-key", b"sk-proj-" + b"A" * 24),
]


@pytest.mark.parametrize("rule,sample", SYNTHETIC_SHAPES)
def test_every_secret_shape_is_private_and_digest_bound(
    rule: str, sample: bytes
) -> None:
    """Every rule rejects synthetic shapes and permits only the exact digest."""
    data = b"Synthetic documentation example\n" + sample + b"\n"
    path = "skills/helper/example.txt"
    with pytest.raises(ValueError) as raised:
        inspect_bytes(data=data, path=path, vendor="synthetic-vendor", allow=())
    assert_that(str(raised.value)).contains(
        "synthetic-vendor", path, ":2:", rule
    ).does_not_contain(sample.decode())
    entry = IngestAllow(
        path=path,
        rule=rule,
        sha256=hashlib.sha256(data).hexdigest(),
        reason="Synthetic documentation example " + sample.decode(),
    )
    findings = inspect_bytes(
        data=data, path=path, vendor="synthetic-vendor", allow=(entry,)
    )
    assert_that(findings).is_length(1)
    assert_that(json.dumps(findings)).does_not_contain(sample.decode()).contains(
        "[REDACTED]"
    )
    for modified, acknowledgement in (
        (data + b"changed", entry),
        (data, replace(entry, path="elsewhere")),
        (data, replace(entry, rule="unknown")),
    ):
        with pytest.raises(ValueError, match="unacknowledged"):
            inspect_bytes(
                data=modified,
                path=path,
                vendor="synthetic-vendor",
                allow=(acknowledgement,),
            )
    assert_that(
        inspect_bytes(
            data=b"binary\0" + sample, path=path, vendor="synthetic-vendor", allow=()
        )
    ).is_empty()


@pytest.mark.parametrize(
    "sample",
    [
        b"AKIA" + b"A" * 15,
        b"ghp_short",
        b"github_pat_short",
        b"xoxb-short",
        b"AIza-short",
        b"npm_short",
        b"sk_test_" + b"A" * 24,
        b"sk-ant-short",
        b"sk-proj-short",
        b"-----BEGIN PUBLIC KEY-----",
    ],
)
def test_near_misses_remain_plain_text(sample: bytes) -> None:
    """Provider prefixes without the documented shape do not trip the scanner."""
    assert_that(
        inspect_bytes(data=sample, path="sample.txt", vendor="synthetic", allow=())
    ).is_empty()


def test_binary_detection_uses_first_eight_kib_only() -> None:
    """A late NUL cannot hide a preceding synthetic shape."""
    data = b"A" * 8192 + b"\n" + SYNTHETIC_SHAPES[3][1] + b"\0"
    with pytest.raises(ValueError, match="aws-access-key-id"):
        inspect_bytes(data=data, path="sample", vendor="synthetic", allow=())


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b""])
def test_lfs_pointer_cannot_be_acknowledged(ending: bytes) -> None:
    """Complete pointers fail without fetching an object, including CRLF."""
    data = (
        b"version https://git-lfs.github.com/spec/v1\noid sha256:"
        + b"a" * 64
        + b"\nsize 123"
        + ending
    )
    with pytest.raises(
        ValueError,
        match="stored in Git LFS; archive contains the pointer, not the content",
    ):
        inspect_bytes(data=data, path="asset.bin", vendor="synthetic", allow=())
    assert_that(
        inspect_bytes(
            data=b"Discussion of " + data, path="docs.md", vendor="synthetic", allow=()
        )
    ).is_empty()


def test_size_is_rejected_before_file_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sparse oversized file is rejected without allocating its contents."""
    path = tmp_path / "huge"
    with path.open("wb") as stream:
        stream.truncate(100_000_000)

    def no_read(**_kwargs: Any) -> bytes:
        """Fail if bounded reading is reached after oversized fstat."""
        pytest.fail("oversized bytes were read")

    monkeypatch.setattr("ai_skills_engine.registry.ingest_checks.read_stream", no_read)
    with pytest.raises(ValueError, match="synthetic.*huge.*fileBytes"):
        read_bounded(path=path, vendor="synthetic", limits=IngestLimits())
    with pytest.raises(ValueError, match="pluginBytes"):
        scan_paths(paths=[(path, "huge")], vendor="synthetic", limits=IngestLimits())


@pytest.mark.parametrize("mode", [0o4644, 0o2644, 0o1644])
def test_special_bits_reject_direct_and_full_bake(
    ingest_repo: tuple[Path, Path, Vendor], mode: int
) -> None:
    """Both public bake entrypoints reject special bits without publishing."""
    root, source, vendor = ingest_repo
    path = source / "skills/helper/hook.sh"
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(mode)
    out = root / "direct"
    with pytest.raises(ValueError, match="special mode bits"):
        bake_vendor_plugins(vendor=vendor, vendor_root=source, output_root=out)
    assert_that(out.exists()).is_false()
    with pytest.raises(ValueError, match="special mode bits"):
        baker.bake(repo_root=root, vendor_trees={vendor.id: source})
    assert_that((root / "plugins-baked").exists()).is_false()


def test_no_vendor_execution_and_canonical_modes(
    ingest_repo: tuple[Path, Path, Vendor], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actual bake copies postinstall/setup/Makefile/hook bytes without executing."""
    root, source, vendor = ingest_repo
    skill = source / "skills/helper"
    sentinel = source.parent / "EXECUTED"
    files = {
        "package.json": json.dumps({"scripts": {"postinstall": f"touch {sentinel}"}}),
        "setup.py": f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n",
        "Makefile": f"all:\n\ttouch {sentinel}\n",
        "hook.sh": f"#!/bin/sh\ntouch {sentinel}\n",
    }
    for name, data in files.items():
        path = skill / name
        path.write_text(data)
        path.chmod(0o775 if name == "hook.sh" else 0o660)

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        """Prohibit all process execution while the real bake runs."""
        pytest.fail("vendor execution attempted")

    for name in (
        "Popen",
        "run",
        "call",
        "check_call",
        "check_output",
        "getoutput",
        "getstatusoutput",
    ):
        monkeypatch.setattr(subprocess, name, forbidden)
    for name in dir(os):
        if name.startswith(("exec", "spawn", "posix_spawn")) or name in {
            "system",
            "popen",
        }:
            monkeypatch.setattr(os, name, forbidden)
    baker.bake(repo_root=root, vendor_trees={vendor.id: source})
    assert_that(baker.check(repo_root=root)).is_zero()
    for name, content in files.items():
        baked = root / "plugins-baked/synthetic-plugin/skills/helper" / name
        assert_that(baked.read_text()).is_equal_to(content)
        assert_that(stat.S_IMODE(baked.stat().st_mode)).is_equal_to(
            0o755 if name == "hook.sh" else 0o644
        )
    assert_that(sentinel.exists()).is_false()


def test_check_rescans_despite_forged_lock_and_hashes(
    ingest_repo: tuple[Path, Path, Vendor], capsys: pytest.CaptureFixture[str]
) -> None:
    """Lock edits, a forged digest and looser limits cannot hide real bytes."""
    root, source, vendor = ingest_repo
    baker.bake(repo_root=root, vendor_trees={vendor.id: source})
    baked = root / "plugins-baked"
    target = baked / "synthetic-plugin/skills/helper/example.txt"
    sample = SYNTHETIC_SHAPES[3][1]
    target.write_bytes(b"Synthetic example\n" + sample)
    target.chmod(0o644)
    path = baked / "BAKE.json"
    lock = json.loads(path.read_text())
    lock["files"][target.relative_to(baked).as_posix()] = hashlib.sha256(
        target.read_bytes()
    ).hexdigest()
    lock["ingestChecks"] = {
        "ruleSetVersion": "forged",
        "vendors": {
            vendor.id: {
                "limits": {"fileBytes": 9999999999999},
                "acknowledgedFindings": [],
            }
        },
    }
    path.write_text(json.dumps(lock))
    before = {file: file.read_bytes() for file in baked.rglob("*") if file.is_file()}
    assert_that(baker.check(repo_root=root)).is_equal_to(1)
    captured = capsys.readouterr()
    assert_that(captured.err).contains("aws-access-key-id").does_not_contain(
        sample.decode()
    )
    assert_that({file: file.read_bytes() for file in before}).is_equal_to(before)


def test_digest_acknowledgement_and_report_roundtrip(
    ingest_repo: tuple[Path, Path, Vendor], capsys: pytest.CaptureFixture[str]
) -> None:
    """Registry-owned acknowledgements survive bake/check and lapse on edit."""
    root, source, vendor = ingest_repo
    target = source / "skills/helper/example.txt"
    sample = SYNTHETIC_SHAPES[3][1]
    target.write_bytes(b"Synthetic documentation\n" + sample)
    # Unselected fixtures are never content-scanned.
    (source / "unselected.txt").write_bytes(sample)
    path = root / "vendors.yaml"
    document = yaml.safe_load(path.read_text())
    document["vendors"][0]["ingestAllow"] = [
        {
            "path": "skills/helper/example.txt",
            "rule": "aws-access-key-id",
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "reason": "Synthetic example " + sample.decode(),
        }
    ]
    document["vendors"][0]["ingestLimits"] = {
        "fileBytes": 6 * 1024 * 1024,
        "reason": "Reviewed synthetic fixture override",
    }
    path.write_text(yaml.safe_dump(document))
    baker.bake(repo_root=root, vendor_trees={vendor.id: source})
    assert_that(baker.check(repo_root=root)).is_zero()
    report = (root / "plugins-baked/COVERAGE.md").read_text()
    lock = json.loads((root / "plugins-baked/BAKE.json").read_text())
    assert_that(report).contains(
        "Ingest checks", "Reviewed synthetic fixture override", "aws-access-key-id"
    ).does_not_contain(sample.decode())
    assert_that(
        lock["ingestChecks"]["vendors"][vendor.id]["acknowledgedFindings"]
    ).is_length(1)
    captured = capsys.readouterr()
    assert_that(captured.out + captured.err).does_not_contain(sample.decode())
    target.write_bytes(target.read_bytes() + b"\nchanged")
    original = (root / "plugins-baked/BAKE.json").read_bytes()
    with pytest.raises(ValueError, match="unacknowledged"):
        baker.bake(repo_root=root, vendor_trees={vendor.id: source})
    assert_that((root / "plugins-baked/BAKE.json").read_bytes()).is_equal_to(original)


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"fileBytes": 1},
        {"fileBytes": True, "reason": "synthetic"},
        {"fileBytes": 0, "reason": "synthetic"},
        {"fileBytes": -1, "reason": "synthetic"},
        {"unknown": 1, "reason": "synthetic"},
        {"fileBytes": 1, "reason": " "},
    ],
)
def test_strict_limit_policy(value: object) -> None:
    """Limit overrides cannot be unbounded, boolean, unknown or unexplained."""
    with pytest.raises(ValueError, match="ingestLimits"):
        parse_limits(value, label="synthetic")


@pytest.mark.parametrize(
    "change",
    [
        {"path": "../escape"},
        {"path": "/absolute"},
        {"path": "skills//a"},
        {"path": "skills/./a"},
        {"path": "a\\b"},
        {"path": "a\0b"},
        {"rule": "unknown"},
        {"sha256": "b" * 40},
        {"reason": " "},
        {"unexpected": True},
    ],
)
def test_strict_acknowledgement_policy(change: dict[str, object]) -> None:
    """Acknowledgements remain closed, canonical and digest-bound."""
    value = {
        "path": "skills/helper/example.txt",
        "rule": "aws-access-key-id",
        "sha256": "a" * 64,
        "reason": "Synthetic example",
        **change,
    }
    with pytest.raises(ValueError, match="ingestAllow"):
        parse_allow([value], label="synthetic")


@pytest.mark.parametrize("limit", ["file_bytes", "plugin_bytes"])
def test_public_bake_limits_preserve_existing_outputs(
    ingest_repo: tuple[Path, Path, Vendor], limit: str
) -> None:
    """Selected byte limits fail in direct ingestion before publishing any output."""
    root, source, vendor = ingest_repo
    output = root / "direct"
    output.mkdir()
    sentinel = output / "sentinel"
    sentinel.write_bytes(b"existing bytes\r\n")
    # Keep fixtures tiny while testing the actual bounded copy path.
    path = source / "skills/helper/oversized.txt"
    path.write_bytes(b"x" * 101)
    overrides: dict[str, Any] = {limit: 100}
    limits = replace(
        vendor.ingest_limits, reason="Synthetic low-limit boundary", **overrides
    )
    from ai_skills_engine.manifest.codec import field_key

    with pytest.raises(ValueError) as raised:
        bake_vendor_plugins(
            vendor=replace(vendor, ingest_limits=limits),
            vendor_root=source,
            output_root=output,
        )
    assert_that(str(raised.value)).contains(
        vendor.id, "oversized.txt", field_key(limit)
    )
    assert_that(list(output.iterdir())).is_equal_to([sentinel])
    assert_that(sentinel.read_bytes()).is_equal_to(b"existing bytes\r\n")


def test_offline_check_validates_policy_when_no_bake_exists(
    ingest_repo: tuple[Path, Path, Vendor], capsys: pytest.CaptureFixture[str]
) -> None:
    """An absent artifact does not let malformed ingestion policy pass --check."""
    root, _source, _vendor = ingest_repo
    path = root / "vendors.yaml"
    data = yaml.safe_load(path.read_text())
    data["vendors"][0]["ingestLimits"] = {
        "fileBytes": True,
        "reason": "Synthetic malformed policy",
    }
    path.write_text(yaml.safe_dump(data))
    assert_that(baker.check(repo_root=root)).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("ingestLimits")


def test_many_repeated_shapes_have_one_digest_bound_finding() -> None:
    """Repeated matches do not allocate a report object or rescan lines per match."""
    sample = SYNTHETIC_SHAPES[3][1]
    data = (sample + b"\n") * 50_000
    entry = IngestAllow(
        path="synthetic.txt",
        rule="aws-access-key-id",
        sha256=hashlib.sha256(data).hexdigest(),
        reason="Synthetic repetition stress control",
    )
    findings = inspect_bytes(
        data=data, path="synthetic.txt", vendor="synthetic", allow=(entry,)
    )
    assert_that(findings).is_length(1)
    assert_that(findings[0]["line"]).is_equal_to(1)


@pytest.mark.parametrize("fetched", [False, True])
@pytest.mark.parametrize(
    "finding", ["lfs", "secret", "special-bits", "fileBytes", "pluginBytes"]
)
def test_actual_acquisition_rejects_before_replacing_bake(
    ingest_repo: tuple[Path, Path, Vendor],
    monkeypatch: pytest.MonkeyPatch,
    fetched: bool,
    finding: str,
) -> None:
    """Real tar and offline ingestion both preserve the last known bake on reject."""
    from inventory_helpers import inventory_tarball

    root, source, vendor = ingest_repo
    baker.bake(repo_root=root, vendor_trees={vendor.id: source})
    output = root / "plugins-baked"
    before = {
        path.relative_to(output): (path.read_bytes(), path.stat().st_mode)
        for path in output.rglob("*")
        if path.is_file()
    }
    inode = output.stat().st_ino
    asset = source / "skills/helper/synthetic.txt"
    asset.write_bytes(b"Synthetic harmless content\n")
    expected = finding
    if finding == "lfs":
        asset.write_bytes(
            b"version https://git-lfs.github.com/spec/v1\noid sha256:"
            + b"a" * 64
            + b"\nsize 123\n"
        )
        expected = "stored in Git LFS"
    elif finding == "secret":
        asset.write_bytes(b"Synthetic example\nAKIA" + b"A" * 16)
        expected = "aws-access-key-id"
    elif finding == "special-bits":
        asset.chmod(0o4644)
        expected = "special mode bits"
    else:
        policy = yaml.safe_load((root / "vendors.yaml").read_text())
        policy["vendors"][0]["ingestLimits"] = {
            finding: 128,
            "reason": "Synthetic actual-ingestion limit control",
        }
        (root / "vendors.yaml").write_text(yaml.safe_dump(policy))
        asset.write_bytes(b"x" * 129)
    if fetched:
        payload = inventory_tarball(source)
        monkeypatch.setattr(baker, "_http_get_bytes", lambda **_kwargs: payload)
    with pytest.raises(ValueError, match=expected):
        baker.bake(
            repo_root=root, vendor_trees=None if fetched else {vendor.id: source}
        )
    assert_that(
        {
            path.relative_to(output): (path.read_bytes(), path.stat().st_mode)
            for path in output.rglob("*")
            if path.is_file()
        }
    ).is_equal_to(before)
    assert_that(output.stat().st_ino).is_equal_to(inode)


def test_unselected_locations_and_alias_notices_are_redacted(
    ingest_repo: tuple[Path, Path, Vendor], capsys: pytest.CaptureFixture[str]
) -> None:
    """Reporting excluded fixtures must not log secret-shaped names or link targets."""
    root, source, vendor = ingest_repo
    # Repeated synthetic provider shapes; neither value is a credential.
    name = "AKIA" + "A" * 16
    target = "ghp_" + "A" * 36
    skipped = source / "ignored" / name
    skipped.mkdir(parents=True)
    (skipped / "SKILL.md").write_text(
        "---\nname: synthetic\ndescription: Excluded fixture.\n---\n"
    )
    (source / "NAVIGATION.md").symlink_to(target)
    baker.bake(repo_root=root, vendor_trees={vendor.id: source})
    assert_that(baker.check(repo_root=root)).is_zero()
    output = capsys.readouterr()
    assert_that(output.out + output.err).does_not_contain(name, target).contains(
        "[REDACTED]"
    )
    for filename in ("COVERAGE.md", "BAKE.json"):
        assert_that((root / "plugins-baked" / filename).read_text()).does_not_contain(
            name, target
        )


def test_acknowledgement_reason_redacts_complete_pem_material() -> None:
    """Privacy covers the whole synthetic PEM block, beyond its matched header."""
    from ai_skills_engine.registry.ingest_checks import safe_diagnostic

    header = b"-" * 5 + b"BEGIN PRIVATE KEY" + b"-" * 5
    footer = b"-" * 5 + b"END PRIVATE KEY" + b"-" * 5
    # Base64 for synthetic text, not private key material or a credential.
    body = b"c3ludGhldGljLW5vdC1hLWtleQ=="
    data = header + b"\n" + body + b"\n" + footer
    acknowledgement = IngestAllow(
        path="example.pem",
        rule="pem-private-key",
        sha256=hashlib.sha256(data).hexdigest(),
        reason="Synthetic example: " + data.decode() + " end of example",
    )
    findings = inspect_bytes(
        data=data, path="example.pem", vendor="synthetic", allow=(acknowledgement,)
    )
    rendered = json.dumps(findings)
    assert_that(rendered).does_not_contain(
        body.decode(), header.decode(), footer.decode()
    ).contains("[REDACTED]", "end of example")
    assert_that(safe_diagnostic(header.decode() * 10_000)).does_not_contain(
        header.decode()
    )
