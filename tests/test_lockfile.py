"""Strict, canonical ``ai-skills.lock`` model boundaries."""

import json
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that

from ai_skills_engine.lockfile import (
    LockFormatError,
    LockKeyError,
    LockVersionError,
    MissingLockError,
    dumps,
    loads,
    read_lock,
    require_canonical,
    write_lock,
)
from ai_skills_engine.lockmodel.builder import Builder
from ai_skills_engine.lockmodel.filters import Filters
from ai_skills_engine.lockmodel.lock import Lock
from ai_skills_engine.lockmodel.locked_capability import LockedCapability
from ai_skills_engine.lockmodel.locked_package import LockedPackage
from ai_skills_engine.lockmodel.locked_resource import LockedResource
from ai_skills_engine.lockmodel.locked_vendor import LockedVendor
from ai_skills_engine.lockmodel.manifest_record import ManifestRecord

DIGEST = "sha256:" + "1" * 64
CHAIN = {
    "attestations": [],
    "id": "fixture/tools:skill/start",
    "lineage": [
        {
            "id": "fixture/tools:skill/start",
            "origin": "github.com/fixture/artifacts",
            "path": "skills/start",
            "publisher": "fixture",
            "renamedFrom": None,
            "rev": None,
            "transforms": [],
            "treeDigest": DIGEST,
        }
    ],
}


@pytest.fixture
def lock() -> Lock:
    """Provide a complete lock with every record type.

    Returns:
        Typed lock.
    """
    return Lock(
        builder=Builder(engine_version="1.2.3", artifact_format=1),
        manifest=ManifestRecord(
            api_version="ai-skills.dev/v1", digest=DIGEST, inputs_digest=DIGEST
        ),
        vendors=(
            LockedVendor(
                id="zeta",
                repo="owner/zeta",
                sha="b" * 40,
                source_digest=DIGEST,
                filters=Filters(include=("skills/*",), exclude=("skills/x",)),
            ),
            LockedVendor(
                id="alpha",
                repo="owner/alpha",
                sha="a" * 40,
                source_digest=DIGEST,
                filters=Filters(),
            ),
        ),
        packages=(
            LockedPackage(
                id="fixture/tools",
                version="0.0.0-local",
                artifact_digest=DIGEST,
                tree_digest=DIGEST,
                capabilities=(
                    LockedCapability(
                        id="fixture/tools:skill/start",
                        closure=("fixture/tools:skill/start",),
                        lineage=(CHAIN,),
                    ),
                ),
                resources=(
                    LockedResource(
                        id="fixture/tools:resource/shared",
                        lineage=({**CHAIN, "id": "fixture/tools:resource/shared"},),
                    ),
                ),
            ),
        ),
    )


def _document(lock: Lock) -> dict[str, Any]:
    """Decode the canonical encoding for mutation.

    Args:
        lock: Typed lock.

    Returns:
        Mutable JSON document.
    """
    return dict(json.loads(dumps(lock)))


def test_canonical_dump_round_trips(lock: Lock) -> None:
    """Sorted keys, 2-space indent and a trailing newline; vendors sorted by ID."""
    data = dumps(lock)
    assert_that(data).is_equal_to(
        (json.dumps(json.loads(data), sort_keys=True, indent=2) + "\n").encode()
    )
    assert_that(data.endswith(b"}\n")).is_true()
    assert_that(data).contains(b'\n  "builder": {\n    "artifactFormat": 1,')
    document = json.loads(data)
    assert_that(document["lockVersion"]).is_equal_to(1)
    assert_that([item["id"] for item in document["vendors"]]).is_equal_to(
        ["alpha", "zeta"]
    )
    parsed = loads(data)
    assert_that(dumps(parsed)).is_equal_to(data)
    assert_that(parsed.packages).is_equal_to(lock.packages)


@pytest.mark.parametrize("version", [2, 0, "1", True, 1.0, None])
def test_unknown_lock_version_fails_clearly(lock: Lock, version: object) -> None:
    """Unknown, non-integer and absent versions never get a best-effort read."""
    document = _document(lock)
    if version is None:
        document.pop("lockVersion")
    else:
        document["lockVersion"] = version
    with pytest.raises(LockVersionError, match="unsupported lockVersion") as error:
        loads(json.dumps(document).encode())
    assert_that(str(error.value)).contains("reads lockVersion 1", "best-effort")


@pytest.mark.parametrize(
    ("pointer", "location"),
    [
        ((), "/"),
        (("builder",), "/builder"),
        (("manifest",), "/manifest"),
        (("vendors", 0), "/vendors/0"),
        (("vendors", 0, "filters"), "/vendors/0/filters"),
        (("packages", 0), "/packages/0"),
        (("packages", 0, "capabilities", 0), "/packages/0/capabilities/0"),
        (("packages", 0, "resources", 0), "/packages/0/resources/0"),
    ],
)
def test_unknown_key_fails_with_location(
    lock: Lock, pointer: tuple[str | int, ...], location: str
) -> None:
    """Every record rejects undefined keys and names where they occur."""
    document = _document(lock)
    target: Any = document
    for part in pointer:
        target = target[part]
    target["x-extra"] = "value"
    with pytest.raises(LockKeyError, match="unknown key 'x-extra'") as error:
        loads(json.dumps(document).encode())
    assert_that(str(error.value)).contains(f"at {location};")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda d: d["manifest"].pop("digest"), "missing key 'digest'"),
        (lambda d: d["builder"].update(artifactFormat="1"), "artifactFormat"),
        (lambda d: d["vendors"][0].update(sha="A" * 40), "/vendors/0/sha"),
        (lambda d: d["vendors"][0].update(repo="../x"), "/vendors/0/repo"),
        (
            lambda d: d["packages"][0].update(artifactDigest="sha1:" + "0" * 40),
            "/packages/0/artifactDigest",
        ),
        (
            lambda d: d["packages"][0]["capabilities"][0].update(closure="x"),
            "closure must be an array",
        ),
        (
            lambda d: d["packages"][0]["capabilities"][0]["lineage"][0].update(id="x"),
            "invalid lineage at /packages/0/capabilities/0/lineage/0",
        ),
        (lambda d: d.update(vendors={}), "/vendors must be an array"),
    ],
)
def test_malformed_values_fail(lock: Lock, mutation: Any, message: str) -> None:
    """Malformed records fail with a format error naming the location."""
    document = _document(lock)
    mutation(document)
    with pytest.raises(LockFormatError, match="ai-skills.lock") as error:
        loads(json.dumps(document).encode())
    assert_that(str(error.value)).contains(message)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"\xff", "not UTF-8"),
        (b"[]", "/ must be an object"),
        (b"{", "invalid JSON"),
        (b'{"lockVersion": 1, "lockVersion": 1}', "duplicate key 'lockVersion'"),
        (b'{"lockVersion": NaN}', "invalid JSON constant NaN"),
    ],
)
def test_malformed_documents_fail(data: bytes, message: str) -> None:
    """Undecodable, non-object, duplicate and non-standard JSON never parse."""
    with pytest.raises(LockFormatError) as error:
        loads(data)
    assert_that(str(error.value)).contains(message)


def test_read_write_are_canonical_and_atomic(lock: Lock, tmp_path: Path) -> None:
    """Writes publish only changed canonical bytes and leave no temporary files."""
    path = tmp_path / "ai-skills.lock"
    with pytest.raises(MissingLockError, match="run `ai-skills-engine lock`"):
        read_lock(path)
    assert_that(write_lock(path=path, lock=lock)).is_true()
    assert_that(write_lock(path=path, lock=lock)).is_false()
    assert_that([item.name for item in tmp_path.iterdir()]).is_equal_to(
        ["ai-skills.lock"]
    )
    assert_that(read_lock(path)).is_equal_to(loads(dumps(lock)))
    require_canonical(path=path, lock=read_lock(path))
    path.write_bytes(dumps(lock).replace(b"\n", b"\r\n"))
    with pytest.raises(LockFormatError, match="is not canonical"):
        require_canonical(path=path, lock=read_lock(path))
