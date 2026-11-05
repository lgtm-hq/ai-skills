"""Digest pins, artifact verification and schema checks before any write."""

import hashlib
import io
import json
import os
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that
from install_helpers import GOLDEN_DIGEST, profile_path, run

from ai_skills_engine.install import verify
from ai_skills_engine.install.profile import Profile, write_profile
from ai_skills_engine.install.selectors import SelectorKind, make_selector

pytest_plugins = ["install_helpers"]
TAR = "fixture--tools.tar"
WRONG = "sha256:" + "0" * 64


def _snapshot(*roots: Path) -> dict[str, bytes]:
    """Record every file under the given roots.

    Args:
        *roots: Directories to record.

    Returns:
        Path to bytes.
    """
    return {
        str(path): path.read_bytes()
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _rewrite_embedded(golden: Path, change: dict[str, Any]) -> None:
    """Replace the tar's own index and re-publish a matching sidecar.

    Args:
        golden: Writable artifact directory.
        change: Top-level index keys to set.
    """
    source = golden / TAR
    output = io.BytesIO()
    with (
        tarfile.open(fileobj=io.BytesIO(source.read_bytes()), mode="r:") as before,
        tarfile.open(fileobj=output, mode="w:", format=tarfile.PAX_FORMAT) as after,
    ):
        for member in before:
            stream = before.extractfile(member) if member.isfile() else None
            data = stream.read() if stream is not None else b""
            if member.name == "index.json":
                data = json.dumps(json.loads(data) | change).encode()
                member.size = len(data)
            after.addfile(member, io.BytesIO(data) if member.isfile() else None)
    source.write_bytes(output.getvalue())
    digest = hashlib.sha256(output.getvalue()).hexdigest()
    (golden / (TAR + ".sha256")).write_text(f"{digest}  {TAR}\n")


def _corrupt(golden: Path, kind: str) -> str:
    """Break the artifact in one way.

    Args:
        golden: Writable artifact directory.
        kind: Which defect.

    Returns:
        Expected diagnostic fragment.
    """
    index = golden / "index.json"
    if kind == "tar-bytes":
        data = bytearray((golden / TAR).read_bytes())
        data[-1] ^= 1
        (golden / TAR).write_bytes(bytes(data))
        return "digest mismatch: sidecar pin"
    if kind == "catalog-format":
        index.write_text(
            json.dumps(json.loads(index.read_text()) | {"artifactFormat": 2})
        )
        return "unsupported artifactFormat 2"
    if kind == "catalog-field":
        index.write_text(json.dumps(json.loads(index.read_text()) | {"modes": {}}))
        return "'modes' was unexpected"
    if kind == "embedded-format":
        _rewrite_embedded(golden, {"artifactFormat": "1"})
        return 'unsupported artifactFormat "1"'
    if kind == "embedded-field":
        _rewrite_embedded(golden, {"signature": "x"})
        return "'signature' was unexpected"
    if kind == "sidecar":
        (golden / (TAR + ".sha256")).write_text("not a digest\n")
        return "malformed digest sidecar"
    if kind == "no-pin":
        (golden / (TAR + ".sha256")).unlink()
        return "no pinned digest"
    (golden / TAR).unlink()
    return "artifact fixture--tools.tar not found"


@pytest.mark.parametrize(
    "kind",
    [
        "tar-bytes",
        "catalog-format",
        "catalog-field",
        "embedded-format",
        "embedded-field",
        "sidecar",
        "no-pin",
        "missing-tar",
    ],
)
def test_refusals_happen_before_any_write(
    golden: Path, consumer: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    """Mismatches, unknown formats and unknown fields abort with nothing written."""
    message = _corrupt(golden, kind)
    before = _snapshot(golden, consumer)
    status, _, err = run(
        capsys,
        "install",
        "--artifacts",
        str(golden),
        "--exclude",
        "package:fixture/tools",
    )
    assert_that(status).is_equal_to(1)
    assert_that(err).contains(message)
    assert_that(_snapshot(golden, consumer)).is_equal_to(before)
    assert_that(profile_path(consumer).exists()).is_false()


@pytest.mark.parametrize(
    ("present", "winner"),
    [
        (("profile", "lock", "digest"), "profile"),
        (("lock", "digest"), "lock"),
        (("digest",), "digest"),
        ((), "sidecar"),
    ],
)
def test_pin_priority(
    golden: Path,
    consumer: Path,
    capsys: pytest.CaptureFixture[str],
    present: tuple[str, ...],
    winner: str,
) -> None:
    """Profile beats lock beats --digest beats the published sidecar."""
    pins = dict.fromkeys(present, GOLDEN_DIGEST)
    if "profile" in pins:
        write_profile(
            profile_path(consumer), Profile(artifacts={"fixture/tools": WRONG})
        )
    if "lock" in pins:
        lock = {
            "lockVersion": 1,
            "packages": [{"id": "fixture/tools", "artifactDigest": WRONG}],
        }
        (Path.cwd() / "ai-skills.lock").write_text(json.dumps(lock))
    flags = ["--digest", f"fixture/tools={WRONG}"] if "digest" in pins else []
    if winner == "sidecar":
        (golden / (TAR + ".sha256")).write_text(f"{'1' * 64}  {TAR}\n")
    status, _, err = run(capsys, "install", "--artifacts", str(golden), *flags)
    assert_that(status).is_equal_to(1)
    assert_that(err).contains(f"digest mismatch: {winner} pin")


@pytest.mark.parametrize("source", ["profile", "lock", "digest"])
def test_sidecar_is_not_read_when_a_higher_pin_exists(
    golden: Path,
    consumer: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    """A higher-priority pin wins without ever opening the (corrupt) sidecar."""
    (golden / (TAR + ".sha256")).write_bytes(b"\xff\xfe not a sidecar")
    reads: list[str] = []
    original = verify._sidecar

    def spy(directory: Path, package: str) -> str | None:
        """Record any sidecar read before delegating.

        Args:
            directory: Artifact directory.
            package: Package ID.

        Returns:
            The real reader's result.
        """
        reads.append(package)
        return original(directory, package)

    monkeypatch.setattr(verify, "_sidecar", spy)
    flags: list[str] = []
    if source == "profile":
        write_profile(
            profile_path(consumer), Profile(artifacts={"fixture/tools": GOLDEN_DIGEST})
        )
    elif source == "lock":
        lock = {
            "lockVersion": 1,
            "packages": [{"id": "fixture/tools", "artifactDigest": GOLDEN_DIGEST}],
        }
        (Path.cwd() / "ai-skills.lock").write_text(json.dumps(lock))
    else:
        flags = ["--digest", GOLDEN_DIGEST]
    status, report, err = run(
        capsys, "install", "--artifacts", str(golden), "--dry-run", *flags
    )
    assert_that(status).described_as(err).is_zero()
    assert_that(report["packages"][0]["pin"] if report else None).is_equal_to(source)
    assert_that(reads).is_empty()


def _unreadable_sidecar(path: Path, kind: str) -> None:
    """Make an existing sidecar undecodable or unreadable.

    Args:
        path: Sidecar path.
        kind: ``utf8`` for invalid bytes, ``permission`` for mode 000.
    """
    if kind == "utf8":
        path.write_bytes(b"\xff" * 64 + b"  " + TAR.encode() + b"\n")
    else:
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
def test_unreadable_sidecar_is_reported_cleanly(
    golden: Path, consumer: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    """Undecodable or unreadable sidecars are install errors, not tracebacks."""
    sidecar = golden / (TAR + ".sha256")
    _unreadable_sidecar(sidecar, kind)
    try:
        status, _, err = run(capsys, "install", "--artifacts", str(golden))
    finally:
        sidecar.chmod(0o644)
    assert_that(status).is_equal_to(1)
    assert_that(err).contains(f"{sidecar}: unreadable digest sidecar")
    assert_that(err).does_not_contain("Traceback")
    assert_that(profile_path(consumer).exists()).is_false()


def test_each_pin_source_verifies(
    golden: Path, consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A correct pin from any source verifies and is recorded as such."""
    (golden / (TAR + ".sha256")).unlink()
    status, report, _ = run(
        capsys,
        "install",
        "--artifacts",
        str(golden),
        "--digest",
        GOLDEN_DIGEST,
        "--dry-run",
    )
    assert_that(status).is_zero()
    assert_that(report["packages"] if report else None).is_equal_to(
        [{"digest": GOLDEN_DIGEST, "id": "fixture/tools", "pin": "digest"}]
    )
    lock = {
        "lockVersion": 1,
        "packages": [{"id": "fixture/tools", "artifactDigest": GOLDEN_DIGEST}],
    }
    (Path.cwd() / "ai-skills.lock").write_text(json.dumps(lock))
    status, report, _ = run(capsys, "install", "--artifacts", str(golden))
    assert_that(report["packages"][0]["pin"] if report else None).is_equal_to("lock")
    status, report, _ = run(capsys, "install", "--artifacts", str(golden))
    assert_that(report["packages"][0]["pin"] if report else None).is_equal_to("profile")


@pytest.mark.parametrize(
    ("lock", "message"),
    [
        ({"lockVersion": 2, "packages": []}, "unsupported lockVersion 2"),
        ({"lockVersion": 1, "packages": {}}, "packages must be a list"),
        ({"lockVersion": 1, "packages": [{"id": "fixture/tools"}]}, "need id and"),
        (
            {
                "lockVersion": 1,
                "packages": [{"id": "fixture/tools", "artifactDigest": "x"}],
            },
            "artifactDigest is malformed",
        ),
    ],
)
def test_repository_lock_pins_are_strict(
    golden: Path,
    consumer: Path,
    capsys: pytest.CaptureFixture[str],
    lock: dict[str, Any],
    message: str,
) -> None:
    """An unreadable repository lock never falls back to weaker pins."""
    (Path.cwd() / "ai-skills.lock").write_text(json.dumps(lock))
    status, _, err = run(capsys, "install", "--artifacts", str(golden))
    assert_that(status).is_equal_to(1)
    assert_that(err).contains(message)


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--digest", WRONG.replace("sha256:", "md5:")], "expected sha256:<64 hex>"),
        (["--digest", f"other/pkg={GOLDEN_DIGEST}"], "unselected package"),
        (
            ["--digest", WRONG, "--exclude", "capability:absent/x:skill/y"],
            "stale selector",
        ),
        (["--exclude", "skill:fixture/tools"], "invalid exclude"),
        (["--exclude", "package:Fixture"], "invalid package ID"),
        (["--deny-origin", ""], "invalid origin"),
        (["--global", "--project"], "Choose only one scope"),
    ],
)
def test_invalid_flags_are_refused(
    golden: Path,
    consumer: Path,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    message: str,
) -> None:
    """Malformed selectors, origins and digests fail with a specific message."""
    status, _, err = run(capsys, "install", "--artifacts", str(golden), *flags)
    assert_that(status).is_equal_to(1)
    assert_that(err).contains(message)


def test_digest_flag_cannot_contradict_a_recorded_pin(
    golden: Path, consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An explicit --digest that disagrees with the winning pin is an error."""
    write_profile(
        profile_path(consumer), Profile(artifacts={"fixture/tools": GOLDEN_DIGEST})
    )
    status, _, err = run(
        capsys, "install", "--artifacts", str(golden), "--digest", WRONG
    )
    assert_that(status).is_equal_to(1)
    assert_that(err).contains("contradicts the profile pin")


@pytest.mark.parametrize(
    "second",
    [f"fixture/tools={WRONG}", WRONG],
    ids=["qualified", "bare"],
)
def test_conflicting_digest_flags_for_one_package_fail(
    golden: Path, consumer: Path, capsys: pytest.CaptureFixture[str], second: str
) -> None:
    """Two different --digest values for one package never silently pick one."""
    flags = ["--digest", f"fixture/tools={GOLDEN_DIGEST}", "--digest", second]
    status, _, err = run(capsys, "install", "--artifacts", str(golden), *flags)
    assert_that(status).is_equal_to(1)
    assert_that(err).contains(
        f"conflicting --digest values for fixture/tools: {GOLDEN_DIGEST} and {WRONG}"
    )
    assert_that(profile_path(consumer).exists()).is_false()


def test_identical_repeated_digest_flags_are_tolerated(
    golden: Path, consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Repeating the same pin, in either spelling, is not a conflict."""
    flags = ["--digest", f"fixture/tools={GOLDEN_DIGEST}", "--digest", GOLDEN_DIGEST]
    status, report, err = run(
        capsys, "install", "--artifacts", str(golden), "--dry-run", *flags
    )
    assert_that(status).described_as(err).is_zero()
    assert_that(report["packages"] if report else None).is_equal_to(
        [{"digest": GOLDEN_DIGEST, "id": "fixture/tools", "pin": "digest"}]
    )


def test_frozen_installs_only_the_pinned_digest(
    golden: Path, consumer: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--frozen needs a recorded pin, refuses a different digest and writes nothing."""
    status, _, err = run(capsys, "install", "--artifacts", str(golden), "--frozen")
    assert_that(status).is_equal_to(1)
    assert_that(err).contains("--frozen needs a pin in the profile or lock")
    path = profile_path(consumer)
    write_profile(
        path,
        Profile(
            artifacts={"fixture/tools": GOLDEN_DIGEST},
            exclude=(
                make_selector(SelectorKind.CAPABILITY, "fixture/tools:skill/peer"),
                make_selector(SelectorKind.CAPABILITY, "fixture/tools:skill/start"),
            ),
        ),
    )
    recorded = path.read_bytes()
    status, report, _ = run(capsys, "install", "--artifacts", str(golden), "--frozen")
    assert_that(status).is_zero()
    assert_that(report["kept"]["capabilities"] if report else None).is_empty()
    assert_that(report["profile"]["written"] if report else None).is_false()
    _corrupt(golden, "tar-bytes")
    status, _, err = run(capsys, "update", "--artifacts", str(golden), "--frozen")
    assert_that(status).is_equal_to(1)
    assert_that(err).contains("digest mismatch: profile pin " + GOLDEN_DIGEST)
    status, _, err = run(
        capsys, "install", "--artifacts", str(golden), "--frozen", "--deny-origin", "x"
    )
    assert_that(status).is_equal_to(1)
    assert_that(err).contains("--frozen restores recorded pins and selection")
    assert_that(path.read_bytes()).is_equal_to(recorded)
