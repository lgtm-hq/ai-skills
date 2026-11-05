"""Public ``lock``/``build`` commands with a local fake source fetcher, no network."""

import builtins
import hashlib
import io
import json
import os
import re
import shutil
import socket
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.bake import vendor_plugins
from ai_skills_engine.lockfile import read_lock
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.registry.vendor import Vendor
from ai_skills_engine.source_cache import SourceCache

pytest_plugins = ["artifact_helpers"]
PIN = "a" * 40
ENGINE = Path(__file__).resolve().parents[1] / "src/ai_skills_engine"


class Upstream:
    """A local fake forge serving one mutable tree for every pinned fetch.

    Attributes:
        tree: Directory served for the pinned repository.
        calls: ``repo@sha`` of each acquisition.
    """

    def __init__(self, tree: Path) -> None:
        self.tree = tree
        self.calls: list[str] = []

    def fetch(self, *, vendor: Vendor, dest: Path) -> None:
        """Copy the served tree instead of downloading a tarball.

        Args:
            vendor: Requested pin.
            dest: New directory to receive the tree.
        """
        self.calls.append(f"{vendor.repo}@{vendor.sha}")
        shutil.copytree(self.tree, dest, symlinks=True)


def _no_network(*_args: object, **_kwargs: object) -> None:
    """Fail on any network access.

    Raises:
        AssertionError: Always.
    """
    raise AssertionError("network access during an offline operation")


@pytest.fixture
def upstream(
    artifact_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Upstream]:
    """Create a consumer importing the artifact fixture through a fake fetcher.

    Args:
        artifact_repo: Synthetic publication used as the vendor tree.
        tmp_path: Test directory.
        monkeypatch: Patches the fetcher and forbids HTTP.

    Returns:
        Consumer root and the fake upstream.
    """
    served = Upstream(artifact_repo)
    monkeypatch.setattr(vendor_plugins, "_fetch_vendor_tree", served.fetch)
    monkeypatch.setattr(vendor_plugins, "_http_get_bytes", _no_network)
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "ai-skills.yaml").write_text(
        dump_document(
            {
                "apiVersion": "ai-skills.dev/v1",
                "publisher": {"id": "consumer", "repo": "fixture/consumer"},
                "vendors": [
                    {
                        "id": "upstream",
                        "repo": "fixture/artifacts",
                        "sha": PIN,
                        "license": "MIT",
                    }
                ],
                "policy": {"provenance": {"mode": "strict"}},
            }
        )
    )
    return consumer, served


def _run(root: Path, *command: str) -> int:
    """Invoke the public engine CLI.

    Args:
        root: Manifest root.
        command: Subcommand and flags.

    Returns:
        Exit status.
    """
    return cli.main(["--repo-root", str(root), *command])


def _reorder(value: object) -> object:
    """Reverse every mapping's key order recursively.

    Args:
        value: Parsed YAML value.

    Returns:
        Equal value with reversed key insertion order.
    """
    if isinstance(value, dict):
        return {key: _reorder(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [_reorder(item) for item in value]
    return value


def test_lock_is_idempotent_and_key_order_independent(
    upstream: tuple[Path, Upstream], capsys: pytest.CaptureFixture[str]
) -> None:
    """Two locks are byte-identical; reordering YAML keys changes nothing."""
    root, served = upstream
    assert_that(_run(root, "lock")).is_zero()
    path = root / "ai-skills.lock"
    first = path.read_bytes()
    stat = path.stat()
    assert_that(_run(root, "lock")).is_zero()
    assert_that(capsys.readouterr().out).contains("lock: unchanged ai-skills.lock")
    assert_that(path.read_bytes()).is_equal_to(first)
    assert_that(path.stat().st_mtime_ns).is_equal_to(stat.st_mtime_ns)
    manifest = root / "ai-skills.yaml"
    original = manifest.read_text()
    reordered = yaml.safe_dump(
        _reorder(read_document(manifest)), sort_keys=False, indent=4
    )
    assert_that(reordered).is_not_equal_to(original)
    manifest.write_text("---\n# Reordered keys and formatting.\n" + reordered)
    assert_that(_run(root, "lock", "--check")).is_zero()
    assert_that(_run(root, "lock")).is_zero()
    assert_that(path.read_bytes()).is_equal_to(first)
    assert_that(served.calls).is_equal_to([f"fixture/artifacts@{PIN}"])


def test_build_offline_from_warm_cache_matches_lock(
    upstream: tuple[Path, Upstream], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With every acquisition path raising, build reproduces every locked digest."""
    root, _served = upstream
    assert_that(_run(root, "lock")).is_zero()
    for name in ("_fetch_vendor_tree", "_http_get_bytes"):
        monkeypatch.setattr(vendor_plugins, name, _no_network)
    monkeypatch.setattr(socket.socket, "connect", _no_network)
    assert_that(_run(root, "build")).is_zero()
    lock = read_lock(root / "ai-skills.lock")
    output = root / "dist/artifacts"
    index = json.loads((output / "index.json").read_text())
    assert_that(lock.packages).is_not_empty()
    for package in lock.packages:
        name = package.id.replace("/", "--") + ".tar"
        tar = (output / name).read_bytes()
        assert_that("sha256:" + hashlib.sha256(tar).hexdigest()).is_equal_to(
            package.artifact_digest
        )
        assert_that((output / (name + ".sha256")).read_text()).starts_with(
            package.artifact_digest[7:]
        )
        indexed = next(item for item in index["packages"] if item["id"] == package.id)
        assert_that(indexed["treeDigest"]).is_equal_to(package.tree_digest)
        assert_that([item.id for item in package.capabilities]).is_equal_to(
            [item["id"] for item in indexed["capabilities"]]
        )
        for capability, item in zip(
            package.capabilities, indexed["capabilities"], strict=True
        ):
            assert_that(list(capability.lineage)).is_equal_to(item["lineage"])
    assert_that(lock.vendors[0].id).is_equal_to("upstream")
    assert_that(lock.builder.engine_version).is_equal_to(index["engineVersion"])


def _corrupt_cache(cache: Path) -> None:
    """Flip one byte of the cached source.

    Args:
        cache: Cache root.
    """
    entry = next((cache / "sources").glob("*.tar"))
    data = bytearray(entry.read_bytes())
    data[100] ^= 1
    entry.write_bytes(bytes(data))


def _rewrite_lock(root: Path, change: Callable[[dict[str, Any]], None]) -> None:
    """Mutate the decoded lock and store it canonically.

    Args:
        root: Manifest root.
        change: In-place document mutation.
    """
    path = root / "ai-skills.lock"
    document = json.loads(path.read_text())
    change(document)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def _stale_manifest(root: Path) -> None:
    """Change a manifest value without touching the lock.

    Args:
        root: Manifest root.
    """
    manifest = root / "ai-skills.yaml"
    document = read_document(manifest)
    document["vendors"][0]["license"] = "Apache-2.0"
    manifest.write_text(dump_document(document))


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("corrupt-cache", "Corrupted source cache entry for vendor upstream"),
        ("lock-version", "unsupported lockVersion 2"),
        ("unknown-key", "unknown key 'generatedAt' at /"),
        ("stale-manifest", "the ai-skills.yaml manifest digest changed"),
    ],
)
def test_failures_have_distinct_messages(
    upstream: tuple[Path, Upstream],
    isolated_source_cache: Path,
    capsys: pytest.CaptureFixture[str],
    failure: str,
    message: str,
) -> None:
    """Each frozen failure is reported by build and lock --check, not repaired."""
    root, _served = upstream
    assert_that(_run(root, "lock")).is_zero()
    if failure == "corrupt-cache":
        _corrupt_cache(isolated_source_cache)
    elif failure == "lock-version":
        _rewrite_lock(root, lambda document: document.update(lockVersion=2))
    elif failure == "unknown-key":
        _rewrite_lock(root, lambda document: document.update(generatedAt="x"))
    else:
        _stale_manifest(root)
    lock = (root / "ai-skills.lock").read_bytes()
    capsys.readouterr()
    markers = {
        "Corrupted source cache entry",
        "unsupported lockVersion",
        "unknown key",
        "manifest digest changed",
    }
    for command in (["build"], ["lock", "--check"]):
        assert_that(_run(root, *command)).is_equal_to(1)
        error = capsys.readouterr().err
        assert_that(error).contains(message)
        assert_that([item for item in markers if item in error]).is_length(1)
    assert_that((root / "ai-skills.lock").read_bytes()).is_equal_to(lock)
    assert_that((root / "dist/artifacts").exists()).is_false()
    assert_that(list((root / "dist").glob(".ai-skills-build-*"))).is_empty()


def test_cache_miss_names_vendor_and_fetch_fix(
    upstream: tuple[Path, Upstream],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A cold cache fails build offline; lock --fetch fills it for the lock only."""
    root, served = upstream
    assert_that(_run(root, "lock")).is_zero()
    monkeypatch.setenv("AI_SKILLS_CACHE", str(tmp_path / "cold-cache"))
    capsys.readouterr()
    for command in (["build"], ["lock", "--check"]):
        assert_that(_run(root, *command)).is_equal_to(1)
        assert_that(capsys.readouterr().err).contains(
            "Source cache miss for vendor upstream",
            "run `ai-skills-engine lock --fetch`",
        )
    assert_that(served.calls).is_length(1)
    assert_that(_run(root, "lock", "--check", "--inputs-only")).is_zero()
    lock = (root / "ai-skills.lock").read_bytes()
    assert_that(_run(root, "lock", "--fetch")).is_zero()
    assert_that(served.calls).is_length(2)
    assert_that((root / "ai-skills.lock").read_bytes()).is_equal_to(lock)
    assert_that(_run(root, "build")).is_zero()


def test_lock_never_moves_existing_pins(
    upstream: tuple[Path, Upstream],
    artifact_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unchanged pins keep their digest; only changed entries are re-resolved."""
    root, served = upstream
    assert_that(_run(root, "lock")).is_zero()
    path = root / "ai-skills.lock"
    locked = path.read_bytes()
    # The forge now serves different bytes for the same pinned SHA.
    (artifact_repo / "LICENSE").write_text("Changed upstream bytes.\n")
    assert_that(_run(root, "lock")).is_zero()
    assert_that(path.read_bytes()).is_equal_to(locked)
    monkeypatch.setenv("AI_SKILLS_CACHE", str(tmp_path / "cold-cache"))
    capsys.readouterr()
    for command in (["lock"], ["lock", "--fetch"]):
        assert_that(_run(root, *command)).is_equal_to(1)
        assert_that(capsys.readouterr().err).contains(
            "sourceDigest", "but ai-skills.lock records"
        )
    assert_that(path.read_bytes()).is_equal_to(locked)
    assert_that(list((tmp_path / "cold-cache").rglob("*.tar"))).is_empty()
    manifest = root / "ai-skills.yaml"
    document = read_document(manifest)
    document["vendors"][0]["sha"] = "b" * 40
    manifest.write_text(dump_document(document))
    assert_that(_run(root, "lock", "--fetch")).is_zero()
    assert_that(capsys.readouterr().err).contains("is not in ai-skills.lock; skipped")
    assert_that(_run(root, "lock")).is_zero()
    vendor = read_lock(path).vendors[0]
    assert_that(vendor.sha).is_equal_to("b" * 40)
    assert_that(served.calls[-1]).is_equal_to("fixture/artifacts@" + "b" * 40)


def _strings(value: object, key: str = "") -> list[tuple[str, str]]:
    """Collect every key and string value of a JSON document.

    Args:
        value: Decoded JSON.
        key: Key of the current value.

    Returns:
        ``(key, string)`` pairs, including keys themselves.
    """
    if isinstance(value, dict):
        return [
            pair
            for name, item in value.items()
            for pair in [(name, name), *_strings(item, name)]
        ]
    if isinstance(value, list):
        return [pair for item in value for pair in _strings(item, key)]
    return [(key, value)] if isinstance(value, str) else []


def test_lock_contains_no_absolute_paths_or_timestamps(
    upstream: tuple[Path, Upstream], isolated_source_cache: Path
) -> None:
    """Paths are relative and no clock, user or host value is recorded."""
    root, _served = upstream
    assert_that(_run(root, "lock")).is_zero()
    text = (root / "ai-skills.lock").read_text()
    strings = _strings(json.loads(text))
    assert_that(strings).is_not_empty()
    timestamp = re.compile(r"\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2})?|\d{2}:\d{2}:\d{2}")
    machine = {
        str(root),
        str(root.parent),
        str(isolated_source_cache),
        str(Path.home()),
        os.environ.get("USER", "") or "\0",
        socket.gethostname(),
    }
    for key, value in strings:
        assert_that(value.startswith(("/", "~", "\\"))).is_false()
        assert_that(re.match(r"^[A-Za-z]:[\\/]", value)).is_none()
        assert_that(timestamp.search(value)).is_none()
        assert_that(key.lower()).does_not_contain("time", "date", "generated")
        for item in machine:
            if len(item) > 3:
                assert_that(value).does_not_contain(item)


def test_engine_never_touches_v1_gateway_lock_files(
    upstream: tuple[Path, Upstream], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Install-state files stay unread and unwritten; the engine never names them."""
    root, _served = upstream
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    sentinels = [root / "ai-skills-lock.json", home / ".ai-skills/lock.json"]
    for path in sentinels:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"sentinel": true}\n')
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in sentinels}
    opened: list[str] = []
    original_open, original_os_open = builtins.open, os.open

    def tracking_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        """Record high-level opens."""
        opened.append(os.fsdecode(file) if isinstance(file, str | bytes | Path) else "")
        return original_open(file, *args, **kwargs)

    def tracking_os_open(path: Any, *args: Any, **kwargs: Any) -> int:
        """Record low-level opens."""
        opened.append(os.fsdecode(path))
        return original_os_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", tracking_open)
    monkeypatch.setattr(io, "open", tracking_open)
    monkeypatch.setattr(os, "open", tracking_os_open)
    for command in (["lock"], ["lock", "--fetch"], ["lock", "--check"], ["build"]):
        assert_that(_run(root, *command)).is_zero()
    monkeypatch.undo()
    assert_that(opened).is_not_empty()
    assert_that(
        [name for name in opened if name.endswith(("ai-skills-lock.json", "lock.json"))]
    ).is_empty()
    for path, observed in before.items():
        assert_that((path.read_bytes(), path.stat().st_mtime_ns)).is_equal_to(observed)
    for source in ENGINE.rglob("*.py"):
        text = source.read_text()
        assert_that(text).does_not_contain("ai-skills-lock.json", ".ai-skills/lock")


def test_lock_check_writes_nothing(
    upstream: tuple[Path, Upstream], isolated_source_cache: Path
) -> None:
    """The check mode leaves the repository and cache byte-for-byte unchanged."""
    root, _served = upstream
    assert_that(_run(root, "lock")).is_zero()

    def tree() -> dict[str, bytes]:
        """Snapshot the repository and cache.

        Returns:
            Path to bytes for every regular file.
        """
        return {
            str(path): path.read_bytes()
            for base in (root, isolated_source_cache)
            for path in base.rglob("*")
            if path.is_file()
        }

    before = tree()
    assert_that(_run(root, "lock", "--check")).is_zero()
    assert_that(tree()).is_equal_to(before)


def test_supplied_snapshot_must_match_locked_source(
    upstream: tuple[Path, Upstream],
    artifact_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Offline --vendor-tree seeding verifies unchanged pins against the lock."""
    root, served = upstream
    snapshot = tmp_path / "snapshot"
    shutil.copytree(artifact_repo, snapshot, symlinks=True)
    assert_that(_run(root, "lock", "--vendor-tree", f"upstream={snapshot}")).is_zero()
    assert_that(served.calls).is_empty()
    (snapshot / "LICENSE").write_text("Tampered snapshot.\n")
    capsys.readouterr()
    assert_that(
        _run(root, "lock", "--fetch", "--vendor-tree", f"upstream={snapshot}")
    ).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("but ai-skills.lock records")
    assert_that(_run(root, "lock", "--vendor-tree", f"absent={snapshot}")).is_equal_to(
        1
    )
    assert_that(capsys.readouterr().err).contains("Unknown --vendor-root aliases")
    assert_that(_run(root, "build")).is_zero()


def test_supplied_snapshot_is_never_indexed_as_fetched(
    upstream: tuple[Path, Upstream],
    artifact_repo: Path,
    isolated_source_cache: Path,
    tmp_path: Path,
) -> None:
    """A --vendor-tree seed stores bytes but no ref a later lookup would trust."""
    root, served = upstream
    snapshot = tmp_path / "snapshot"
    shutil.copytree(artifact_repo, snapshot, symlinks=True)
    assert_that(_run(root, "lock", "--vendor-tree", f"upstream={snapshot}")).is_zero()
    cache = SourceCache(root=isolated_source_cache)
    locked = read_lock(root / "ai-skills.lock").vendors[0].source_digest
    assert_that(cache.has(locked)).is_true()
    assert_that(cache.lookup(repo="fixture/artifacts", revision=PIN)).is_none()
    assert_that(_run(root, "build")).is_zero()
    assert_that(served.calls).is_empty()


@pytest.mark.parametrize(
    "damage",
    [
        "lock-version",
        "conflict-markers",
    ],
)
def test_damaged_lock_names_regeneration_path(
    upstream: tuple[Path, Upstream],
    capsys: pytest.CaptureFixture[str],
    damage: str,
) -> None:
    """Plain ``lock`` cannot repair an unreadable lock, so it says how to recover."""
    root, _served = upstream
    assert_that(_run(root, "lock")).is_zero()
    path = root / "ai-skills.lock"
    if damage == "lock-version":
        _rewrite_lock(root, lambda document: document.update(lockVersion=2))
    else:
        path.write_text("<<<<<<< ours\n" + path.read_text() + ">>>>>>> theirs\n")
    damaged = path.read_bytes()
    capsys.readouterr()
    for command in (["lock"], ["lock", "--fetch"]):
        assert_that(_run(root, *command)).is_equal_to(1)
        assert_that(capsys.readouterr().err).contains(
            "to regenerate it, delete ai-skills.lock and run `ai-skills-engine lock`"
        )
    assert_that(path.read_bytes()).is_equal_to(damaged)
    path.unlink()
    assert_that(_run(root, "lock")).is_zero()


def test_build_cache_miss_creates_no_output_directory(
    upstream: tuple[Path, Upstream],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Output parents are created only after every locked source is available."""
    root, _served = upstream
    assert_that(_run(root, "lock")).is_zero()
    monkeypatch.setenv("AI_SKILLS_CACHE", str(tmp_path / "cold-cache"))
    assert_that(_run(root, "build")).is_equal_to(1)
    assert_that((root / "dist").exists()).is_false()


@pytest.mark.parametrize("failing", ["", "--fetch", "--check", "build"])
def test_ci_publish_and_validate_gate_on_the_lock(tmp_path: Path, failing: str) -> None:
    """CI and publish fetch, check and build from the lock; any step fails closed."""
    import subprocess  # nosec B404 - fixed local gate script, no shell

    root = ENGINE.parents[1]
    publish = (root / ".github/workflows/publish-npm.yml").read_text()
    steps = [
        "run: uv run ai-skills-engine lock --fetch",
        "run: uv run ai-skills-engine lock --check",
        "run: uv run ai-skills-engine build",
    ]
    positions = [publish.index(step) for step in steps]
    assert_that(positions).is_sorted()
    assert_that(publish).does_not_contain("--fetch-vendors", "--write-digests")
    jobs = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())["jobs"]
    gate = jobs["lock-build"]["with"]
    assert_that(gate["script"]).is_equal_to("scripts/ci/lock_build_gate.sh")
    assert_that(gate["allowed-endpoints"]).contains("codeload.github.com:443")
    assert_that((root / "scripts/validate.sh").read_text()).contains(
        "uv run ai-skills-engine lock --check --inputs-only"
    )
    assert_that((root / "artifact-digests.json").exists()).is_false()
    calls = tmp_path / "calls"
    fake = tmp_path / "bin/uv"
    fake.parent.mkdir()
    fake.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$CALLS"\n'
        'case "$*" in *"$FAILING") [ -n "$FAILING" ] && exit 9 ;; esac\n'
        "exit 0\n"
    )
    fake.chmod(0o755)
    bash = shutil.which("bash")
    assert_that(bash).is_not_none()
    result = subprocess.run(  # nosec B603 - fixed local script and fake uv
        [str(bash), str(root / "scripts/ci/lock_build_gate.sh")],
        env={
            "PATH": f"{fake.parent}{os.pathsep}{os.environ['PATH']}",
            "CALLS": str(calls),
            "FAILING": failing,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    expected = [
        "run ai-skills-engine lock --fetch",
        "run ai-skills-engine lock --check",
        "run ai-skills-engine build",
    ]
    stop = {"": 3, "--fetch": 1, "--check": 2, "build": 3}[failing]
    assert_that(result.returncode).is_equal_to(9 if failing else 0)
    assert_that(calls.read_text().splitlines()).is_equal_to(expected[:stop])


def test_lock_and_build_accept_a_symlinked_temporary_root(
    upstream: tuple[Path, Upstream],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scratch under a symlinked TMPDIR (macOS ``/var``) is not an output link."""
    root, _served = upstream
    real = tmp_path / "real-tmp"
    real.mkdir()
    link = tmp_path / "linked-tmp"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(tempfile, "tempdir", str(link))
    assert_that(_run(root, "lock")).is_zero()
    assert_that(_run(root, "lock", "--check")).is_zero()
    assert_that(_run(root, "build")).is_zero()
    assert_that(list(real.iterdir())).is_empty()
