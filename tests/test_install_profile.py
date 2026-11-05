"""Consumer profile persistence, update replay and stale selectors."""

import os
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from assertpy import assert_that
from install_helpers import build_two_hop, profile_path, run

from ai_skills_engine import cli
from ai_skills_engine.install.errors import InstallError
from ai_skills_engine.install.profile import (
    Profile,
    default_path,
    load_profile,
    parse_profile,
    write_profile,
)

pytest_plugins = ["artifact_helpers", "install_helpers"]
OWN = "capability:z/tools:skill/own"
VENDOR_Q = "github.com/fixture/q"
API = "apiVersion: ai-skills.dev/selection/v1\n"


def _add_extra(document: dict[str, Any], z: Path) -> None:
    """Publish a changed Z package that still contains every old ID.

    Args:
        document: Z manifest.
        z: Z snapshot root.
    """
    (z / "skills/extra").mkdir()
    (z / "skills/extra/SKILL.md").write_text(
        "---\nname: extra\ndescription: Fixture.\n---\n\n# Extra\n"
    )
    document["packages"][0]["capabilities"].append(
        {"id": "extra", "path": "skills/extra"}
    )


def _drop_own(document: dict[str, Any], z: Path) -> None:
    """Publish a Z package without ``own``.

    Args:
        document: Z manifest.
        z: Z snapshot root (unchanged).
    """
    del z
    document["packages"][0]["capabilities"] = [
        item for item in document["packages"][0]["capabilities"] if item["id"] != "own"
    ]


def _install(capsys: pytest.CaptureFixture[str], artifacts: Path) -> dict[str, Any]:
    """Install excluding ``own`` and denying an absent origin.

    Args:
        capsys: Output capture.
        artifacts: Artifact directory.

    Returns:
        Install report.
    """
    status, report, err = run(
        capsys,
        "install",
        "--artifacts",
        str(artifacts),
        "--exclude",
        OWN,
        "--deny-origin",
        VENDOR_Q,
    )
    assert_that(status).described_as(err).is_zero()
    return report or {}


def test_install_persists_excludes_denies_and_pins(
    tmp_path: Path, consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The profile records every package pin plus the consumer's choices."""
    artifacts = build_two_hop(tmp_path / "src", tmp_path / "out")
    report = _install(capsys, artifacts)
    path = profile_path(consumer)
    assert_that(report["profile"]).is_equal_to({"path": str(path), "written": True})
    document = yaml.safe_load(path.read_text())
    assert_that(document).is_equal_to(
        {
            "apiVersion": "ai-skills.dev/selection/v1",
            "artifacts": {item["id"]: item["digest"] for item in report["packages"]},
            "exclude": [{"capability": "z/tools:skill/own"}],
            "deny": [{"origin": VENDOR_Q}],
            "modes": {},
        }
    )
    assert_that(sorted(document["artifacts"])).is_equal_to(
        ["x/tools", "y/tools", "z/tools"]
    )
    assert_that(report["kept"]["capabilities"]).does_not_contain("z/tools:skill/own")
    assert_that(sorted(path.parent.iterdir())).is_equal_to([path])


def test_update_replays_profile_against_a_new_artifact(
    tmp_path: Path, consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``update`` moves pins to the new digests and keeps the old excludes."""
    old = build_two_hop(tmp_path / "old-src", tmp_path / "old")
    before = _install(capsys, old)
    new = build_two_hop(tmp_path / "new-src", tmp_path / "new", _add_extra)
    status, _, err = run(capsys, "install", "--artifacts", str(new))
    assert_that(status).is_equal_to(1)
    assert_that(err).contains("z/tools: digest mismatch: profile pin")
    status, report, err = run(capsys, "update", "--artifacts", str(new))
    assert_that(status).described_as(err).is_zero()
    report = report or {}
    pins = {item["id"]: item["digest"] for item in report["packages"]}
    old_pins = {item["id"]: item["digest"] for item in before["packages"]}
    assert_that(pins["z/tools"]).is_not_equal_to(old_pins["z/tools"])
    assert_that(report["kept"]["capabilities"]).contains("z/tools:skill/extra")
    assert_that(report["kept"]["capabilities"]).does_not_contain("z/tools:skill/own")
    assert_that(load_profile(profile_path(consumer)).artifacts).is_equal_to(pins)


@pytest.mark.parametrize("dry", [True, False])
def test_stale_selector_fails_update_by_name(
    tmp_path: Path, consumer: Path, capsys: pytest.CaptureFixture[str], dry: bool
) -> None:
    """A persisted exclude that no longer matches anything stops the update."""
    _install(capsys, build_two_hop(tmp_path / "old-src", tmp_path / "old"))
    path = profile_path(consumer)
    recorded = path.read_bytes()
    new = build_two_hop(tmp_path / "new-src", tmp_path / "new", _drop_own)
    flags = ["--dry-run"] if dry else []
    status, _, err = run(capsys, "update", "--artifacts", str(new), *flags)
    assert_that(status).is_equal_to(1)
    assert_that(err).contains(f"stale selector matches nothing: profile {OWN}")
    assert_that(path.read_bytes()).is_equal_to(recorded)


def test_stale_package_pin_fails_update(
    tmp_path: Path, consumer: Path, golden: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A recorded package missing from the new artifact is named."""
    _install(capsys, build_two_hop(tmp_path / "src", tmp_path / "out"))
    status, _, err = run(capsys, "update", "--artifacts", str(golden))
    assert_that(status).is_equal_to(1)
    assert_that(err).contains("stale profile entry: artifacts.x/tools")


def test_update_without_profile_and_dry_run(
    golden: Path, consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``update`` needs an install first; ``--dry-run`` never writes."""
    status, _, err = run(capsys, "update", "--artifacts", str(golden))
    assert_that(err).contains("profile records no artifacts")
    status, report, _ = run(capsys, "install", "--artifacts", str(golden), "--dry-run")
    assert_that(status).is_zero()
    assert_that(report["profile"]["written"] if report else None).is_false()
    assert_that(profile_path(consumer).exists()).is_false()


def test_profile_write_is_atomic(
    golden: Path,
    consumer: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed rename leaves the old profile intact and no temporary file."""
    path = profile_path(consumer)
    write_profile(path, Profile())
    recorded = path.read_bytes()

    def interrupted(*_args: object) -> None:
        """Simulate a crash between write and rename.

        Raises:
            OSError: Always.
        """
        raise OSError("interrupted")

    monkeypatch.setattr("ai_skills_engine.atomic_write.os.replace", interrupted)
    status = cli.main(["install", "--artifacts", str(golden)])
    captured = capsys.readouterr()
    assert_that(status).is_equal_to(1)
    assert_that(captured.err).contains(f"cannot write profile {path}: interrupted")
    assert_that(captured.out).is_empty()
    assert_that(path.read_bytes()).is_equal_to(recorded)
    assert_that(sorted(item.name for item in path.parent.iterdir())).is_equal_to(
        [path.name]
    )


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="needs POSIX directory permissions enforced for a non-root user",
)
def test_unwritable_profile_directory_is_reported_without_traceback(
    golden: Path, consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A read-only config directory yields a diagnostic and exit status 1."""
    path = profile_path(consumer)
    path.parent.mkdir(parents=True)
    path.parent.chmod(0o555)
    try:
        status, report, err = run(capsys, "install", "--artifacts", str(golden))
    finally:
        path.parent.chmod(0o755)
    assert_that(status).is_equal_to(1)
    assert_that(report).is_none()
    assert_that(err).starts_with(f"install: cannot write profile {path}: ")
    assert_that(err).does_not_contain("Traceback")
    assert_that(path.exists()).is_false()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("apiVersion: ai-skills.dev/selection/v2\n", "apiVersion must be"),
        ("apiVersion: ai-skills.dev/selection/v1\nextra: 1\n", "unknown key"),
        (
            "apiVersion: ai-skills.dev/selection/v1\nmodes: {codex: user-explode}\n",
            "modes is reserved",
        ),
        ("apiVersion: a\napiVersion: b\n", "duplicate key"),
        (
            "apiVersion: ai-skills.dev/selection/v1\nartifacts: {x/y: sha256:00}\n",
            "expected sha256",
        ),
        (
            (
                "apiVersion: ai-skills.dev/selection/v1\n"
                "exclude: [{resource: x/y:resource/z}]\n"
            ),
            "unknown profile exclude kind",
        ),
        ("apiVersion: ai-skills.dev/selection/v1\ndeny: [github.com/x]\n", "origin"),
        ("- not a mapping\n", "expected a mapping"),
        (f"{API}artifacts: 0\n", "artifacts must be a mapping"),
        (f"{API}artifacts: false\n", "artifacts must be a mapping"),
        (f"{API}exclude: ''\n", "exclude must be a list"),
        (f"{API}exclude: 0\n", "exclude must be a list"),
        (f"{API}deny: false\n", "deny must be a list"),
        (f"{API}deny: ''\n", "deny must be a list"),
        (f"{API}modes: 0\n", "modes is reserved"),
    ],
)
def test_profile_reading_is_strict(text: str, message: str) -> None:
    """Unknown versions, keys, reserved data and malformed values fail."""
    with pytest.raises(InstallError, match=message):
        parse_profile(text, source="selection.yaml")


@pytest.mark.parametrize(
    "body",
    [
        "",
        "artifacts:\nexclude:\ndeny:\nmodes:\n",
        "artifacts: null\nexclude: ~\ndeny: null\nmodes: null\n",
    ],
    ids=["absent", "empty-values", "explicit-null"],
)
def test_absent_or_null_fields_mean_empty(body: str) -> None:
    """The documented contract: absent and YAML ``null`` fields are empty."""
    assert_that(parse_profile(API + body, source="selection.yaml")).is_equal_to(
        Profile()
    )


def _unreadable_profile(path: Path, kind: str) -> None:
    """Write a profile that cannot be decoded or opened.

    Args:
        path: Profile path.
        kind: ``utf8`` for invalid bytes, ``permission`` for mode 000.
    """
    path.parent.mkdir(parents=True)
    if kind == "utf8":
        path.write_bytes(API.encode() + b"deny: [{origin: \xff\xfe}]\n")
    else:
        write_profile(path, Profile())
        path.chmod(0o000)


@pytest.mark.parametrize(
    "kind",
    [
        "utf8",
        pytest.param(
            "permission",
            marks=pytest.mark.skipif(
                sys.platform == "win32" or os.geteuid() == 0,
                reason="needs POSIX file permissions enforced for a non-root user",
            ),
        ),
    ],
)
def test_unreadable_profile_is_reported_cleanly(
    golden: Path, consumer: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    """Undecodable or unreadable profiles exit 1 with a diagnostic, not a traceback."""
    path = profile_path(consumer)
    _unreadable_profile(path, kind)
    try:
        status, report, err = run(capsys, "install", "--artifacts", str(golden))
    finally:
        path.chmod(0o644)
    assert_that(status).is_equal_to(1)
    assert_that(report).is_none()
    assert_that(err).starts_with(f"install: {path}: unreadable profile (")
    assert_that(err).does_not_contain("Traceback")


def test_profile_location_honours_absolute_xdg_only(tmp_path: Path) -> None:
    """A relative ``XDG_CONFIG_HOME`` is ignored, as for the source cache."""
    home = tmp_path / "home"
    assert_that(default_path(env={}, home=home)).is_equal_to(
        home / ".config/ai-skills/selection.yaml"
    )
    assert_that(default_path(env={"XDG_CONFIG_HOME": "rel"}, home=home)).is_equal_to(
        home / ".config/ai-skills/selection.yaml"
    )
    assert_that(
        default_path(env={"XDG_CONFIG_HOME": str(tmp_path / "cfg")}, home=home)
    ).is_equal_to(tmp_path / "cfg/ai-skills/selection.yaml")


def test_text_report_lists_verification_and_kept_set(
    golden: Path, consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without ``--json`` the report is one tab-separated record per line."""
    status = cli.main(
        [
            "install",
            "--artifacts",
            str(golden),
            "--exclude",
            "package:fixture/tools",
            "-a",
            "codex",
            "-y",
            "--global",
        ]
    )
    lines = capsys.readouterr().out.splitlines()
    assert_that(status).is_zero()
    assert_that(lines[0]).starts_with("verified\tfixture/tools\tsha256:")
    assert_that(lines[1:3]).is_equal_to(
        [
            "remove\tfixture/tools:resource/shared\texcluded by package:fixture/tools",
            "remove\tfixture/tools:skill/peer\texcluded by package:fixture/tools",
        ]
    )
    assert_that(lines[-1]).is_equal_to(
        f"install: profile written: {profile_path(consumer)}"
    )
