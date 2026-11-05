"""Upstream resolution, baseline reading and CLI argument boundaries of repin."""

import json
import os
import shutil
import subprocess  # nosec B404 - local git fixture, fixed argv, no shell
from dataclasses import replace
from pathlib import Path

import pytest
from assertpy import assert_that
from repin_helpers import NEW_SHA, NEWER_SHA, consumer_document

from ai_skills_engine.bake import vendor_plugins
from ai_skills_engine.registry.vendor import Vendor
from ai_skills_engine.repin.run import vendor_record
from ai_skills_engine.vendors import repin

VENDOR: Vendor = vendor_record(consumer_document()["vendors"][0])


@pytest.mark.parametrize("display_ref", ["latest", None, "HEAD"])
def test_resolve_uses_default_branch_for_floating_refs(
    monkeypatch: pytest.MonkeyPatch, display_ref: str | None
) -> None:
    """A floating display ref tracks the GitHub default branch HEAD."""
    vendor = replace(VENDOR, branch=None, display_ref=display_ref)

    def fake_get(*, host: str, path: str, headers: dict[str, str]) -> bytes:
        del host, headers
        if path.endswith("/commits/main"):
            return json.dumps({"sha": NEW_SHA}).encode()
        if path == f"/repos/{vendor.repo}":
            return json.dumps({"default_branch": "main"}).encode()
        raise AssertionError(path)

    monkeypatch.setattr(vendor_plugins, "_http_get_bytes", fake_get)
    assert_that(repin.resolve_upstream_sha(vendor=vendor)).is_equal_to(NEW_SHA)


@pytest.mark.parametrize(
    ("display_ref", "encoded"),
    [("v1.2.3", "v1.2.3"), ("heads/feature/foo", "heads%2Ffeature%2Ffoo")],
)
def test_resolve_encodes_display_ref(
    monkeypatch: pytest.MonkeyPatch, display_ref: str, encoded: str
) -> None:
    """Other display refs resolve as one percent-encoded git ref."""
    vendor = replace(VENDOR, branch=None, display_ref=display_ref)

    def fake_get(*, host: str, path: str, headers: dict[str, str]) -> bytes:
        del host, headers
        assert_that(path).ends_with(f"/commits/{encoded}")
        return json.dumps({"sha": NEW_SHA.upper()}).encode()

    monkeypatch.setattr(vendor_plugins, "_http_get_bytes", fake_get)
    assert_that(repin.resolve_upstream_sha(vendor=vendor)).is_equal_to(NEW_SHA)


@pytest.mark.parametrize("branch", ["stable", "release/next"])
def test_resolve_prefers_explicit_branch_over_same_name_tag(
    monkeypatch: pytest.MonkeyPatch, branch: str
) -> None:
    """An explicit branch resolves through refs/heads, never a same-name tag."""
    vendor = replace(VENDOR, branch=branch, display_ref=branch)
    encoded = branch.replace("/", "%2F")

    def fake_get(*, host: str, path: str, headers: dict[str, str]) -> bytes:
        del host, headers
        if path == f"/repos/{vendor.repo}/commits/refs%2Fheads%2F{encoded}":
            return json.dumps({"sha": NEW_SHA}).encode()
        return json.dumps({"sha": NEWER_SHA}).encode()

    monkeypatch.setattr(vendor_plugins, "_http_get_bytes", fake_get)
    assert_that(repin.resolve_upstream_sha(vendor=vendor)).is_equal_to(NEW_SHA)


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"sha": "not-a-sha"}, ValueError),
        ({"sha": 7}, TypeError),
        (["not", "an", "object"], TypeError),
    ],
)
def test_resolve_rejects_malformed_payloads(
    monkeypatch: pytest.MonkeyPatch, payload: object, error: type[Exception]
) -> None:
    """Malformed GitHub responses fail instead of producing a pin."""
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-token")

    def fake_get(*, host: str, path: str, headers: dict[str, str]) -> bytes:
        del host, path
        assert_that(headers["Authorization"]).is_equal_to("Bearer fixture-token")
        return json.dumps(payload).encode()

    monkeypatch.setattr(vendor_plugins, "_http_get_bytes", fake_get)
    with pytest.raises(error):
        repin.resolve_upstream_sha(vendor=replace(VENDOR, branch="main"))


def test_resolve_requires_default_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """A repository payload without a default branch fails closed."""
    monkeypatch.setattr(
        vendor_plugins, "_http_get_bytes", lambda **_kwargs: b'{"default_branch": ""}'
    )
    with pytest.raises(RuntimeError, match="default_branch"):
        repin.resolve_upstream_sha(vendor=replace(VENDOR, branch=None))


@pytest.mark.parametrize("ref", ["", "-HEAD", "abc:ai-skills.yaml"])
def test_baseline_ref_rejects_option_like_refs(tmp_path: Path, ref: str) -> None:
    """Refs that look like options or pathspecs never reach git."""
    with pytest.raises(ValueError, match="invalid baseline-ref"):
        repin.baseline_at_ref(repo_root=tmp_path, git_ref=ref)


def test_baseline_ref_must_resolve(tmp_path: Path) -> None:
    """An unknown revision fails with the baseline named."""
    with pytest.raises(RuntimeError, match="could not resolve baseline-ref"):
        repin.baseline_at_ref(repo_root=tmp_path, git_ref="does-not-exist")


def test_baseline_ref_preserves_committed_bytes(tmp_path: Path) -> None:
    """CRLF manifests and locks round-trip byte for byte from the baseline."""
    git = shutil.which("git")
    assert_that(git).described_as("git executable on PATH").is_not_none()
    manifest = b"apiVersion: ai-skills.dev/v1\r\npublisher:\r\n  id: x\r\n"
    lock = b'{\r\n  "lockVersion": 1\r\n}\r\n'
    (tmp_path / "ai-skills.yaml").write_bytes(manifest)
    (tmp_path / "ai-skills.lock").write_bytes(lock)
    config = ["-c", "core.autocrlf=false", "-c", "commit.gpgsign=false"]
    identity = ["-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid"]
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    for argv in (
        ["init", "-q"],
        ["add", "-A"],
        [*identity, "commit", "-q", "-m", "base"],
    ):
        subprocess.run(  # nosec B603 - resolved local git, fixed argv
            [str(git), *config, *argv],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            env=env,
        )
    baseline = repin.baseline_at_ref(repo_root=tmp_path, git_ref="HEAD")
    assert_that(baseline.manifest_text.encode("utf-8")).is_equal_to(manifest)
    assert_that(baseline.lock_bytes).is_equal_to(lock)


@pytest.mark.parametrize(
    "argv",
    [
        ["--baseline-ref", "abc123"],
        ["--all", "--revision", NEW_SHA],
        ["--vendor", "example", "--keep-sha", "--revision", NEW_SHA],
    ],
)
def test_argument_errors(argv: list[str]) -> None:
    """Selections and revision flags are validated before any work."""
    with pytest.raises(SystemExit):
        repin.main(argv)


def test_manifest_is_required(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Re-pinning needs the lock model's manifest."""
    (tmp_path / "vendors.yaml").write_text("vendors: []\n", encoding="utf-8")
    assert_that(
        repin.main(["--repo-root", str(tmp_path), "--vendor", "example"])
    ).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("requires ai-skills.yaml")


def test_gh_runner_failures_are_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing gh, failing gh and non-list output fail with clear errors."""
    from ai_skills_engine.repin import declined

    monkeypatch.setattr(declined.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="gh is required"):
        declined.run_gh(["pr", "list"])
    monkeypatch.setattr(declined.shutil, "which", lambda _name: "/usr/bin/gh")

    def failing(*_args: object, **_kwargs: object) -> None:
        raise declined.subprocess.CalledProcessError(4, ["gh"])

    monkeypatch.setattr(declined.subprocess, "run", failing)
    with pytest.raises(RuntimeError, match="status 4"):
        declined.run_gh(["pr", "list"])
    with pytest.raises(TypeError, match="JSON list"):
        declined.declined_pr(
            vendor="example", revision=NEW_SHA, runner=lambda _argv: "{}"
        )
