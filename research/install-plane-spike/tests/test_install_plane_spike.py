"""Exercise both throwaway runtimes against shared data, without network access."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess  # nosec B404 - fixed local prototypes, no shell or network
import sys
import tarfile
from collections.abc import Buffer, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest
import spike_helpers
from assertpy import assert_that
from spike_helpers import SPIKE

non_utf8_locale = spike_helpers.non_utf8_locale
prototype = spike_helpers.prototype
spike_fixture = spike_helpers.spike_fixture


@pytest.mark.parametrize("variant", ["py", "ts"])
@pytest.mark.parametrize("escaped", [False, True])
@pytest.mark.parametrize(
    "case", json.loads((SPIKE / "invalid-index-keys.json").read_bytes())
)
def test_duplicate_index_keys_rejected(
    spike_fixture: Path,
    tmp_path: Path,
    variant: str,
    escaped: bool,
    case: dict[str, str],
) -> None:
    """Both CLIs reject duplicate fields, including escaped-equivalent keys."""
    bun = shutil.which("bun")
    if variant == "ts" and bun is None:
        if os.environ.get("SPIKE_REQUIRE_BUN") == "1":
            pytest.fail("Bun required for duplicate-index parity")
        pytest.skip("Bun unavailable for duplicate-index parity")
    path = spike_fixture / "index.json"
    key = case["key"]
    repeated = f"\\u{ord(key[0]):04x}{key[1:]}" if escaped else key
    raw = path.read_text(encoding="utf-8").replace(
        f'"{key}":', f'"{key}": {case["previous"]}, "{repeated}":', 1
    )
    path.write_text(raw, encoding="utf-8")
    argv = (
        [sys.executable, "-I", "-B", str(SPIKE / "py/prototype.py")]
        if variant == "py"
        else [str(bun), "run", str(SPIKE / "ts/prototype.ts")]
    )
    result = subprocess.run(  # nosec B603 - fixed offline CLI and bounded fixture
        args=[*argv, str(spike_fixture), "fixture:drop"],
        env={**os.environ, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )
    assert_that(result.returncode).is_equal_to(1)
    assert_that(result.stderr).contains("duplicate index key").does_not_contain(
        "Traceback"
    )
    assert_that(result.stdout).is_empty()
    assert_that((tmp_path / ".spike-target").exists()).is_false()


@pytest.mark.parametrize("failure", ["mkdir", "write"])
def test_failed_output_cleans_and_retries(
    prototype: ModuleType,
    spike_fixture: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """Reachable output I/O failures leave neither final nor staging residue."""
    home = tmp_path / "home"
    home.mkdir()
    original_mkdir, original_write = Path.mkdir, Path.write_bytes

    def mkdir(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        """Fail at the output directory boundary after staging starts."""
        if path.is_relative_to(home) and path.name == "keep":
            raise OSError("injected output failure")
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    def write(path: Path, data: Buffer) -> int:
        """Fail after writing partial output bytes to exercise rollback."""
        if path.is_relative_to(home) and path.name == "SKILL.md":
            original_write(path, b"partial bytes before failure")
            raise OSError("injected output failure")
        return original_write(path, data)

    with monkeypatch.context() as patch:
        if failure == "mkdir":
            patch.setattr(Path, "mkdir", mkdir)
        else:
            patch.setattr(Path, "write_bytes", write)
        with pytest.raises(OSError, match="injected output failure"):
            prototype.install(fixture=spike_fixture, home=home, exclude="fixture:drop")
    assert_that(list(home.iterdir())).is_empty()
    expected = json.loads((spike_fixture / "expected-output.json").read_bytes())
    assert_that(
        prototype.install(fixture=spike_fixture, home=home, exclude="fixture:drop")
    ).is_equal_to(expected)
    assert_that([path.name for path in home.iterdir()]).is_equal_to([".spike-target"])


@pytest.mark.parametrize("occupied", [False, True])
def test_existing_target_is_preserved(
    prototype: ModuleType, spike_fixture: Path, tmp_path: Path, occupied: bool
) -> None:
    """A pre-existing empty or owned target is never overwritten or removed."""
    target = tmp_path / ".spike-target"
    target.mkdir()
    if occupied:
        (target / "owned").write_bytes(b"preserve me")
    with pytest.raises(FileExistsError):
        prototype.install(fixture=spike_fixture, home=tmp_path, exclude="fixture:drop")
    assert_that(target.is_dir()).is_true()
    assert_that([p.name for p in tmp_path.iterdir()]).contains_only(
        "fixture", ".spike-target"
    )
    if occupied:
        assert_that((target / "owned").read_bytes()).is_equal_to(b"preserve me")
    else:
        assert_that(list(target.iterdir())).is_empty()


def test_postpublication_cleanup_failure_reports_cli_success(
    prototype: ModuleType,
    spike_fixture: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A late cleanup error warns, leaving a complete successful CLI install."""
    home = tmp_path / "home"
    home.mkdir()
    rmtree = shutil.rmtree

    def remove(path: Path, *args: object, **kwargs: object) -> None:
        """Fail real TemporaryDirectory removal, leaving its empty staging tree."""
        if Path(path).name.startswith(".spike-stage-"):
            raise OSError("injected staging cleanup failure")
        rmtree(path)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(sys, "argv", ["prototype", str(spike_fixture), "fixture:drop"])
    with monkeypatch.context() as patch:
        patch.setattr(shutil, "rmtree", remove)
        assert_that(prototype.main()).is_zero()
    captured = capsys.readouterr()
    expected = json.loads((spike_fixture / "expected-output.json").read_bytes())
    assert_that(json.loads(captured.out)).is_equal_to(expected)
    assert_that(captured.err).contains(
        "Installation completed; staging cleanup failed:",
        "injected staging cleanup failure",
    )
    for name, content in expected.items():
        assert_that((home / ".spike-target" / name).read_bytes()).is_equal_to(
            content.encode("utf-8")
        )
    # A completed installation is occupied, rather than a failed retryable install.
    assert_that(prototype.main()).is_equal_to(1)
    assert_that(capsys.readouterr().out).is_empty()
    residue = list(home.glob(".spike-stage-*"))
    assert_that(residue).is_length(1)
    assert_that(list(residue[0].iterdir())).is_empty()
    rmtree(residue[0])
    assert_that([path.name for path in home.iterdir()]).contains_only(".spike-target")
    for name, content in expected.items():
        assert_that((home / ".spike-target" / name).read_bytes()).is_equal_to(
            content.encode("utf-8")
        )


@pytest.mark.parametrize(
    ("boundary", "rollback_fails"),
    [
        ("write", False),
        ("publication", False),
        ("publication", True),
        ("existing", False),
    ],
)
@pytest.mark.parametrize("error_type", [OSError, ValueError])
def test_prepublication_failures_retain_evidence_and_cli_status(
    prototype: ModuleType,
    spike_fixture: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    boundary: str,
    rollback_fails: bool,
    error_type: type[Exception],
) -> None:
    """Original, rollback and cleanup errors survive, with honest state and retry."""
    original_error = error_type("injected original installation failure")
    rollback_error = OSError("injected target rollback failure")
    cleanup_error = OSError("injected staging cleanup failure")
    rmtree = shutil.rmtree
    expected = json.loads((spike_fixture / "expected-output.json").read_bytes())
    for entrypoint in ("api", "cli"):
        home = tmp_path / entrypoint
        home.mkdir()
        target = home / ".spike-target"
        if boundary == "existing":
            target.mkdir()
            (target / "owned").write_bytes(b"preserve me")

        def fail_output(*args: object, **kwargs: object) -> None:
            """Fail the selected write or publication operation before commit."""
            raise original_error

        def remove(
            path: Path,
            *args: object,
            owned_target: Path = target,
            **kwargs: object,
        ) -> None:
            """Inject staging cleanup and optional owned-target rollback failures."""
            if Path(path).name.startswith(".spike-stage-"):
                raise cleanup_error
            if path == owned_target and rollback_fails:
                raise rollback_error
            rmtree(path)

        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(
            sys, "argv", ["prototype", str(spike_fixture), "fixture:drop"]
        )
        with monkeypatch.context() as patch:
            patch.setattr(shutil, "rmtree", remove)
            if boundary != "existing":
                patch.setattr(
                    Path,
                    "write_bytes" if boundary == "write" else "rename",
                    fail_output,
                )
            if entrypoint == "api":
                with pytest.raises(ExceptionGroup) as observed:
                    prototype.install(
                        fixture=spike_fixture, home=home, exclude="fixture:drop"
                    )
                errors = observed.value.exceptions
                if boundary == "existing":
                    assert_that(errors[0]).is_instance_of(FileExistsError)
                else:
                    assert_that(errors[0]).is_same_as(original_error)
                assert_that(observed.value.__cause__).is_same_as(errors[0])
                assert_that(errors[-1]).is_same_as(cleanup_error)
                assert_that(errors).is_length(3 if rollback_fails else 2)
                if rollback_fails:
                    assert_that(errors[1]).is_same_as(rollback_error)
            else:
                assert_that(prototype.main()).is_equal_to(1)
                captured = capsys.readouterr()
                assert_that(captured.out).is_empty()
                assert_that(captured.err).contains(str(cleanup_error))
                if boundary != "existing":
                    assert_that(captured.err).contains(str(original_error))
                if rollback_fails:
                    assert_that(captured.err).contains(str(rollback_error))
                assert_that(captured.err).does_not_contain("Traceback")
        residue = list(home.glob(".spike-stage-*"))
        assert_that(residue).is_length(1)
        if boundary == "existing":
            assert_that((target / "owned").read_bytes()).is_equal_to(b"preserve me")
            assert_that(prototype.main()).is_equal_to(1)
            capsys.readouterr()
            rmtree(residue[0])
            continue
        assert_that(target.exists()).is_equal_to(rollback_fails)
        if rollback_fails:
            assert_that(list(target.iterdir())).is_empty()
            assert_that(prototype.main()).is_equal_to(1)
            capsys.readouterr()
            rmtree(target)
        assert_that(prototype.main()).is_zero()
        assert_that(json.loads(capsys.readouterr().out)).is_equal_to(expected)
        rmtree(residue[0])
        assert_that([path.name for path in home.iterdir()]).contains_only(
            ".spike-target"
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "archive",
        "file",
        "closure",
        "missing-closure",
        "unknown-closure",
        "path",
        "duplicate",
        "case-file",
        "case-directory",
        "file-directory",
        "reserved-file",
        "reserved-directory",
    ],
)
def test_spike_rejects_before_writing(
    prototype: ModuleType,
    spike_fixture: Path,
    tmp_path: Path,
    mutation: str,
) -> None:
    """Digest, closure and inventory failures leave no target tree."""
    path = spike_fixture / "index.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    keep = next(cap for cap in index["capabilities"] if cap["id"] == "fixture:keep")
    if mutation == "archive":
        index["sha256"] = "0" * 64
    elif mutation == "file":
        keep["files"]["keep/SKILL.md"] = "0" * 64
    elif mutation == "closure":
        keep["closure"] = ["fixture:drop"]
    elif mutation == "missing-closure":
        del keep["closure"]
    elif mutation == "unknown-closure":
        keep["closure"] = ["fixture:missing"]
    elif mutation == "path":
        keep["files"] = {"../escape": "0" * 64}
    elif mutation == "duplicate":
        index["capabilities"].append(keep)
    elif mutation == "case-file":
        index["capabilities"][0]["files"]["keep/skill.MD"] = "0" * 64
    elif mutation == "case-directory":
        keep["files"]["KEEP/other.md"] = "0" * 64
    elif mutation == "file-directory":
        keep["files"]["keep/SKILL.md/child"] = "0" * 64
    elif mutation == "reserved-file":
        keep["files"]["keep/nUl.txt"] = "0" * 64
    elif mutation == "reserved-directory":
        keep["files"]["COM1/child.md"] = "0" * 64
    path.write_text(json.dumps(index), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        prototype.install(fixture=spike_fixture, home=tmp_path, exclude="fixture:drop")
    assert_that((tmp_path / ".spike-target").exists()).is_false()


@pytest.mark.parametrize("variant", ["py", "ts"])
@pytest.mark.parametrize(
    "mutation", ["nested", "long", "deep", "depth-boundary", "length-boundary"]
)
def test_adversarial_index_cli(
    spike_fixture: Path, tmp_path: Path, variant: str, mutation: str
) -> None:
    """Bounded adversarial indexes fail for the intended reason before writes."""
    index_path = spike_fixture / "index.json"
    if mutation == "nested":
        # 200001 bytes triggers the actual 3.14 C parser's stack guard, while
        # older CPython reaches its recursion guard substantially earlier.
        raw = "[" * 100000 + "0" + "]" * 100000
        reason = "index nesting too deep"
    else:
        name = {
            "long": "a/" + "b" * 9999,
            "deep": "a/" * 5000 + "b",
            "depth-boundary": "a/" * 16 + "b",
            "length-boundary": "a/" + "b" * 99,
        }[mutation]
        index = json.loads(index_path.read_bytes())
        index["capabilities"][0]["files"] = {name: "0" * 64}
        raw = json.dumps(index)
        reason = (
            "path depth limit" if mutation == "depth-boundary" else "path length limit"
        )
    assert_that(len(raw.encode())).is_less_than(1024 * 1024)
    index_path.write_text(raw, encoding="utf-8")
    bun = shutil.which("bun")
    if variant == "ts" and bun is None:
        if os.environ.get("SPIKE_REQUIRE_BUN") == "1":
            pytest.fail("Bun required for adversarial CLI parity")
        pytest.skip("Bun unavailable for adversarial CLI parity")
    argv = (
        [sys.executable, "-I", "-B", str(SPIKE / "py/prototype.py")]
        if variant == "py"
        else [str(bun), "run", str(SPIKE / "ts/prototype.ts")]
    )

    def limit_parser() -> None:
        """Cap the actual Python CLI's address space/CPU on Linux hosts."""
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))

    result = subprocess.run(  # nosec B603 - fixed local CLI; small bounded inputs
        args=[*argv, str(spike_fixture), "fixture:drop"],
        env={**os.environ, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
        preexec_fn=(
            limit_parser if sys.platform == "linux" and variant == "py" else None
        ),
    )
    assert_that(result.returncode).is_equal_to(1)
    assert_that(result.stderr).contains(reason).does_not_contain("Traceback")
    assert_that(result.stdout).is_empty()
    assert_that((tmp_path / ".spike-target").exists()).is_false()


@pytest.mark.parametrize("name", ["a/" + "b" * 98, "a/" * 15 + "b"])
def test_path_profile_inclusive_boundaries(prototype: ModuleType, name: str) -> None:
    """The tiny USTAR profile accepts exactly 100 ASCII bytes and 16 components."""
    assert_that(prototype.safe_path(name)).is_equal_to(name)


@pytest.mark.parametrize("required", [False, True])
def test_adversarial_bun_policy_without_bun(tmp_path: Path, required: bool) -> None:
    """Real pytest runs keep Python checks and skip or fail only Bun cases."""
    env = {
        key: value for key, value in os.environ.items() if key != "SPIKE_REQUIRE_BUN"
    }
    env["PATH"] = str(tmp_path)  # Empty tool directory; Python uses its absolute path.
    if required:
        env["SPIKE_REQUIRE_BUN"] = "1"
    result = subprocess.run(  # nosec B603 - fixed local pytest, no tools or network
        args=[
            sys.executable,
            "-m",
            "pytest",
            str(Path(__file__).resolve()),
            "-q",
            "-o",
            "addopts=",
            "-k",
            "test_adversarial_index_cli",
        ],
        cwd=SPIKE.parents[1],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    output = result.stdout + result.stderr
    assert_that(result.returncode).described_as(output).is_equal_to(
        1 if required else 0
    )
    summary = re.search(r"^(?:=+ )?(\d+ .+?) in [\d.]+s(?: =+)?$", output, re.MULTILINE)
    if summary is None:
        pytest.fail("Missing exact pytest summary: " + output)
    counts = {
        status: int(count)
        for count, status in re.findall(r"(\d+) (passed|failed|skipped)", summary[1])
    }
    assert_that(counts).is_equal_to(
        {"passed": 5, "failed" if required else "skipped": 5}
    )
    assert_that(output).does_not_contain("FileNotFoundError", "Traceback")
    if required:
        assert_that(output).contains("Bun required for adversarial CLI parity")


@pytest.mark.parametrize("variant", ["py", "ts"])
@pytest.mark.parametrize(
    "raw_type",
    [
        tarfile.XHDTYPE,
        tarfile.XGLTYPE,
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_LONGLINK,
    ],
)
def test_empty_extension_before_valid_ustar_is_rejected(
    prototype: ModuleType,
    spike_fixture: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
    raw_type: bytes,
) -> None:
    """An empty raw extension cannot hide behind an inventoried regular member."""
    extension = tarfile.TarInfo("keep/extension")
    extension.type = raw_type
    extension.size = 0
    archive_path = spike_fixture / "artifact.tar"
    archive = extension.tobuf(format=tarfile.USTAR_FORMAT) + archive_path.read_bytes()
    assert_that(len(archive)).is_less_than(16384)
    archive_path.write_bytes(archive)
    index_path = spike_fixture / "index.json"
    index = json.loads(index_path.read_bytes())
    index["sha256"] = hashlib.sha256(archive).hexdigest()
    index_path.write_text(json.dumps(index), encoding="utf-8")
    if variant == "py":

        def interpreted(*args: object, **kwargs: object) -> None:
            """Forbid interpreting extensions even when tarfile would hide them."""
            pytest.fail("raw extension reached tarfile interpretation")

        monkeypatch.setattr(prototype.tarfile, "open", interpreted)
        with pytest.raises(ValueError, match="invalid archive inventory"):
            prototype.install(
                fixture=spike_fixture, home=tmp_path, exclude="fixture:drop"
            )
    else:
        bun = shutil.which("bun")
        if bun is None:
            if os.environ.get("SPIKE_REQUIRE_BUN") == "1":
                pytest.fail("Bun required for empty-extension parity")
            pytest.skip("Bun unavailable for empty-extension parity")
        result = subprocess.run(  # nosec B603 - fixed local CLI, bounded fixture
            args=[
                bun,
                "run",
                str(SPIKE / "ts/prototype.ts"),
                str(spike_fixture),
                "fixture:drop",
            ],
            env={**os.environ, "HOME": str(tmp_path)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        assert_that(result.returncode).is_equal_to(1)
        assert_that(result.stderr).contains("invalid archive inventory")
    assert_that((tmp_path / ".spike-target").exists()).is_false()


@pytest.mark.parametrize("variant", ["py", "ts"])
@pytest.mark.parametrize(
    "mutation",
    [
        "bom-index",
        "invalid-utf8-id",
        "trailing-header",
        "bad-trailer",
        "bad-checksum",
        "extra-member",
        "pax-header",
        "gnu-header",
        "high-bit-header",
        "short-zero-tail",
        "nul-name-suffix",
        "nul-prefix-suffix",
        "invalid-mode",
        "invalid-uid",
        "invalid-gid",
        "invalid-mtime",
        "nul-number-suffix",
        "empty-size",
    ],
)
def test_shared_malformed_inputs_fail_closed(
    spike_fixture: Path, tmp_path: Path, mutation: str, variant: str
) -> None:
    """Both source CLIs reject malformed index/archive bytes before writing."""
    index_path = spike_fixture / "index.json"
    if mutation in {"bom-index", "invalid-utf8-id"}:
        raw = index_path.read_bytes()
        index_path.write_bytes(
            b"\xef\xbb\xbf" + raw
            if mutation == "bom-index"
            else raw.replace(b"fixture:keep", b"fixture:\xffkeep")
        )
    else:
        archive_path = spike_fixture / "artifact.tar"
        archive = archive_path.read_bytes()
        index = json.loads(index_path.read_text(encoding="utf-8"))
        if mutation == "bad-trailer":
            archive = archive[:-1] + b"x"
        elif mutation == "bad-checksum":
            archive = b"x" + archive[1:]  # Keep the stored checksum unchanged.
        elif mutation == "short-zero-tail":
            archive += b"\0"
        elif mutation in {
            "high-bit-header",
            "nul-name-suffix",
            "nul-prefix-suffix",
            "invalid-mode",
            "invalid-uid",
            "invalid-gid",
            "invalid-mtime",
            "nul-number-suffix",
            "empty-size",
            "trailing-header",
        }:
            if mutation == "empty-size":
                # A real zero-length member with a matching inventory would pass
                # Python's old empty-size coercion. Avoid a later digest failure.
                buffer = io.BytesIO()
                with (
                    tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source,
                    tarfile.open(
                        fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT
                    ) as output,
                ):
                    for number, member in enumerate(source):
                        if number == 0:
                            member.size = 0
                            for cap in index["capabilities"]:
                                if member.name in cap["files"]:
                                    cap["files"][member.name] = hashlib.sha256(
                                        b""
                                    ).hexdigest()
                            output.addfile(member, io.BytesIO(b""))
                        else:
                            output.addfile(member, source.extractfile(member))
                archive = buffer.getvalue()
            header = bytearray(archive[:512])
            if mutation == "high-bit-header":
                header[0] |= 0x80
            elif mutation == "trailing-header":
                header[511] = ord("x")
            elif mutation == "nul-name-suffix":
                header[99] = ord("x")
            elif mutation == "nul-prefix-suffix":
                header[346] = ord("x")
            elif mutation == "empty-size":
                header[124:136] = b"\0" * 12
            elif mutation == "nul-number-suffix":
                header[100:108] = b"000\0" + b"001\0"
            else:
                header[
                    {
                        "invalid-mode": 100,
                        "invalid-uid": 108,
                        "invalid-gid": 116,
                        "invalid-mtime": 136,
                    }[mutation]
                ] = ord("8")
            header[148:156] = b" " * 8
            header[148:156] = f"{sum(header):06o}\0 ".encode()
            archive = bytes(header) + archive[512:]
        else:
            buffer = io.BytesIO()
            with tarfile.open(
                fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT
            ) as output:
                with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
                    for member in source:
                        output.addfile(member, source.extractfile(member))
                member = tarfile.TarInfo("keep/extra.md")
                member.type = {
                    "extra-member": tarfile.REGTYPE,
                    "pax-header": tarfile.XHDTYPE,
                    "gnu-header": tarfile.GNUTYPE_LONGNAME,
                }[mutation]
                member.size = 1
                output.addfile(member, io.BytesIO(b"x"))
            archive = buffer.getvalue()
        archive_path.write_bytes(archive)
        index["sha256"] = hashlib.sha256(archive).hexdigest()
        index_path.write_text(json.dumps(index), encoding="utf-8", newline="\n")
    bun = shutil.which("bun")
    if variant == "ts" and bun is None:
        if os.environ.get("SPIKE_REQUIRE_BUN") == "1":
            pytest.fail("Bun required for shared malformed-input parity")
        pytest.skip("Bun unavailable for shared malformed-input parity")
    argv = (
        [sys.executable, "-I", str(SPIKE / "py/prototype.py")]
        if variant == "py"
        else [str(bun), "run", str(SPIKE / "ts/prototype.ts")]
    )
    home = tmp_path / variant
    home.mkdir()
    result = subprocess.run(  # nosec B603 - local fail-closed prototypes
        args=[*argv, str(spike_fixture), "fixture:drop"],
        env={**os.environ, "HOME": str(home)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert_that(result.returncode).described_as(variant + result.stdout).is_not_zero()
    common_reasons = {
        "bad-trailer": "invalid archive trailer",
        "short-zero-tail": "invalid archive length",
        "nul-name-suffix": "nonzero bytes after archive string terminator",
        "nul-prefix-suffix": "invalid archive inventory",
        "nul-number-suffix": "invalid archive number",
        "empty-size": "invalid archive number",
        "pax-header": "invalid archive inventory",
        "gnu-header": "invalid archive inventory",
        "high-bit-header": "non-ASCII archive header",
        "trailing-header": "invalid archive inventory",
    }
    runtime_reasons = {
        "py": {
            "bom-index": "UTF-8 BOM",
            "invalid-utf8-id": "utf-8",
            "extra-member": "invalid archive inventory",
            "bad-checksum": "invalid archive checksum",
        },
        "ts": {
            "bom-index": "JSON Parse error",
            "invalid-utf8-id": "utf-8",
            "extra-member": "incomplete archive",
            "bad-checksum": "invalid archive inventory",
        },
    }
    reason = common_reasons.get(mutation) or runtime_reasons[variant].get(mutation)
    if reason is None:
        reason = "invalid archive number"
    assert_that(result.stderr).described_as(variant + ":" + mutation).contains(
        reason
    ).does_not_contain("Traceback")
    assert_that((home / ".spike-target").exists()).is_false()


@pytest.fixture
def measurement(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import measurement helpers directly from this checkout.

    Args:
        monkeypatch: Reversible local helper import path.

    Returns:
        The spike's stdlib-only command and observation helpers.
    """
    monkeypatch.syspath_prepend(str(SPIKE / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "spike_measurement",
        SPIKE / "scripts/common.py",
    )
    if spec is None or spec.loader is None:
        raise ValueError("cannot load local measurement helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_spike_missing_command_is_unverified(
    measurement: ModuleType,
    tmp_path: Path,
) -> None:
    """A command that cannot launch must not be recorded as exit zero."""
    records: list[dict[str, object]] = []
    result = measurement.command(
        argv=[str(tmp_path / "absent-executable")],
        cwd=tmp_path,
        records=records,
    )
    assert_that(result["exit"]).is_none()
    assert_that(result["stderr"]).is_not_empty()
    assert_that(records).is_length(1)


def test_spike_measurement_rejects_hollow_success(
    measurement: ModuleType,
    spike_fixture: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exit-zero process printing golden JSON without writing files fails."""
    expected = json.loads(
        (spike_fixture / "expected-output.json").read_text(encoding="utf-8")
    )
    root = tmp_path / "payload"
    root.mkdir()
    shutil.copytree(src=spike_fixture, dst=root / "fixtures")

    def fake_command(**kwargs: object) -> dict[str, object]:
        """Model a process lying about a successful install.

        Args:
            kwargs: Unused command arguments.

        Returns:
            Success-looking stdout with no filesystem effects.
        """
        return {"exit": 0, "stdout": json.dumps(expected), "seconds": 0.01}

    monkeypatch.setattr(measurement, "command", fake_command)
    observed = measurement.run_payload(
        root=root,
        variant="py",
        home=tmp_path / "home",
        records=[],
    )
    assert_that(observed["status"]).is_equal_to("fail")


def test_spike_fixture_drift_gate() -> None:
    """The checked-in data artifact exactly matches its deterministic generator."""
    result = subprocess.run(  # nosec B603 - local stdlib generator, no network
        args=[sys.executable, str(SPIKE / "scripts/fixture.py"), "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=10,
    )
    assert_that(result.returncode).described_as(result.stdout + result.stderr).is_zero()


@pytest.mark.parametrize("filename", ["index.json", "artifact.tar"])
def test_fixture_read_is_bounded_before_parse_or_hash(
    prototype: ModuleType,
    spike_fixture: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
) -> None:
    """A sparse oversized input consumes only LIMIT+1 bytes and performs no parsing."""
    path = spike_fixture / filename
    with path.open("wb") as stream:
        stream.truncate(64 * prototype.LIMIT)
    original_open = Path.open
    reads: list[tuple[int, int]] = []

    @contextmanager
    def opened(
        file: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> Iterator[object]:
        """Observe real file reads without allocating the full sparse input.

        Args:
            file: File opened by the installer.
            mode: Original open mode.
            buffering: Original buffering option.
            encoding: Original encoding.
            errors: Original decoder error handling.
            newline: Original newline handling.

        Yields:
            Real stream or a size-observing read boundary.
        """
        with original_open(
            file,
            mode=mode,
            buffering=buffering,
            encoding=encoding,
            errors=errors,
            newline=newline,
        ) as stream:
            if file != path:
                yield stream
                return

            def read(size: int = -1) -> bytes:
                """Check the bound before allowing any allocation.

                Args:
                    size: Requested read budget.

                Returns:
                    Real bounded file bytes.
                """
                assert_that(size).is_between(0, prototype.LIMIT + 1)
                data = stream.read(size)
                if not isinstance(data, bytes):
                    pytest.fail("fixture stream was not binary")
                reads.append((size, len(data)))
                return data

            from types import SimpleNamespace

            yield SimpleNamespace(read=read)

    def forbidden(*args: object, **kwargs: object) -> None:
        """Reject parsing/hashing before input bounds are checked.

        Args:
            args: Ignored parser input.
            kwargs: Ignored parser options.
        """
        pytest.fail("oversized fixture reached parsing or hashing")

    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(prototype.json, "loads", forbidden)
    monkeypatch.setattr(prototype.hashlib, "sha256", forbidden)
    with pytest.raises(ValueError, match="fixture too large"):
        prototype.install(fixture=spike_fixture, home=tmp_path, exclude="fixture:drop")
    assert_that(reads).is_equal_to([(prototype.LIMIT + 1, prototype.LIMIT + 1)])
    assert_that((tmp_path / ".spike-target").exists()).is_false()
