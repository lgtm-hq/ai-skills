"""Synthetic vendor snapshots shared by ingestion boundary tests."""

import hashlib
import tarfile
from io import BytesIO
from pathlib import Path

import pytest
import yaml

from ai_skills_engine.registry.registry import load_registry
from ai_skills_engine.registry.vendor import Vendor


@pytest.fixture(
    params=[
        "nested-file",
        "explicit-root",
        "top-file",
        "top-empty",
        "mixed-file",
        "mixed-empty",
        "top-symlink",
        "private-top-file",
        "two-roots-collision",
        "two-roots-distinct",
        "inconsistent-root-directory",
        "late-inconsistent-root-directory",
        "two-root-directories",
        "private-first-root",
        "private-second-root",
    ],
)
def root_archive(request: pytest.FixtureRequest) -> tuple[bytes, str | None]:
    """Build real gzip archives with valid roots or invalid root layouts.

    Args:
        request: Root layout or invalid member arrangement.

    Returns:
        Compressed archive bytes and the expected rejection, if any.
    """
    kind = request.param
    accepted = kind in {"nested-file", "explicit-root"}
    inconsistent = kind in {
        "two-roots-collision",
        "two-roots-distinct",
        "inconsistent-root-directory",
        "late-inconsistent-root-directory",
        "two-root-directories",
        "private-first-root",
        "private-second-root",
    }
    private_root = "root-" + "AKIA" + "A" * 16
    first_root = private_root if kind == "private-first-root" else "root"
    output = BytesIO()
    # Avoid letting tiny, zero-filled tar padding trip the independent ratio
    # limit before these fixtures reach root-layout validation.
    with tarfile.open(fileobj=output, mode="w:gz", compresslevel=0) as archive:
        if kind in {
            "explicit-root",
            "inconsistent-root-directory",
            "two-root-directories",
        }:
            root = tarfile.TarInfo(
                "other" if kind == "inconsistent-root-directory" else first_root
            )
            root.type = tarfile.DIRTYPE
            root.mode = 0o755
            archive.addfile(root)
        if (accepted or inconsistent or kind.startswith("mixed-")) and (
            kind != "two-root-directories"
        ):
            member = tarfile.TarInfo(f"{first_root}/asset.txt")
            member.mode = 0o644
            data = b"actual fixture payload\n"
            member.size = len(data)
            archive.addfile(member, BytesIO(data))
        if accepted or kind in {
            "two-roots-collision",
            "two-roots-distinct",
            "private-first-root",
            "private-second-root",
        }:
            second_root = (
                first_root
                if accepted
                else private_root if kind == "private-second-root" else "other"
            )
            name = "asset.txt" if kind == "two-roots-collision" else "other.txt"
            member = tarfile.TarInfo(f"{second_root}/{name}")
            member.mode = 0o644
            data = b"second fixture payload\n"
            member.size = len(data)
            archive.addfile(member, BytesIO(data))
        if kind in {"late-inconsistent-root-directory", "two-root-directories"}:
            root = tarfile.TarInfo("other")
            root.type = tarfile.DIRTYPE
            root.mode = 0o755
            archive.addfile(root)
        if not accepted and not inconsistent:
            name = (
                "loose-" + "AKIA" + "A" * 16 + ".txt"
                if kind == "private-top-file"
                else "loose.txt"
            )
            member = tarfile.TarInfo(name)
            member.mode = 0o644
            data = b"" if kind.endswith("empty") else b"misplaced payload\n"
            if kind == "top-symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = "root/asset.txt"
                data = b""
            member.size = len(data)
            archive.addfile(member, BytesIO(data))
    error = None if accepted else "common root" if inconsistent else "top-level"
    return output.getvalue(), error


@pytest.fixture(params=[False, True], ids=["absent", "existing"])
def archive_destination(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    """Provide an absent publication parent or a tree with protected bytes/modes.

    Args:
        tmp_path: Isolated scratch directory.
        request: Whether the destination already exists.

    Returns:
        Destination whose original state must survive rejected extraction.
    """
    destination = tmp_path / "publication/tree"
    if request.param:
        destination.mkdir(parents=True)
        destination.chmod(0o750)
        sentinel = destination / "sentinel"
        sentinel.write_bytes(b"\x00original sentinel\xff\n")
        sentinel.chmod(0o640)
    return destination


@pytest.fixture
def ingest_repo(tmp_path: Path) -> tuple[Path, Path, Vendor]:
    """Build one minimal vendor slice and its local author registry.

    Args:
        tmp_path: Isolated scratch directory.

    Returns:
        Author root, vendor tree and parsed policy.
    """
    root = tmp_path / "author"
    root.mkdir()
    source = tmp_path / "vendor"
    skill = source / "skills/helper"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: helper\ndescription: Synthetic test fixture.\n---\n"
    )
    registry = {
        "vendors": [
            {
                "id": "synthetic-vendor",
                "repo": "synthetic/vendor",
                "sha": "a" * 40,
                "skillRoots": ["skills"],
                "license": "MIT",
                "homepage": "https://example.invalid",
                "plugins": [
                    {
                        "id": "synthetic-plugin",
                        "description": "Synthetic fixture.",
                        "skillsRoot": "skills",
                        "skills": "*",
                    }
                ],
            }
        ]
    }
    (root / "vendors.yaml").write_text(yaml.safe_dump(registry))
    return root, source, load_registry(registry_path=root / "vendors.yaml")[0]


@pytest.fixture(
    params=[
        pytest.param((kind, newline), id=f"{kind}-{style}")
        for kind in (
            "ordinary",
            "complete",
            "unterminated",
            "adjacent-complete",
            "multiple-complete",
            "complete-then-unterminated",
            "adjacent-unterminated",
        )
        for style, newline in (
            ("lf", "\n"),
            ("crlf", "\r\n"),
            ("cr", "\r"),
            ("inline", ""),
        )
    ],
)
def pem_acknowledgement(
    ingest_repo: tuple[Path, Path, Vendor], request: pytest.FixtureRequest
) -> str:
    """Write synthetic PEM reasons into real digest-bound consumer policy.

    Args:
        ingest_repo: Synthetic author root, vendor tree and parsed policy.
        request: Named block arrangement and newline variant.

    Returns:
        Exact public reason expected after redaction.
    """
    kind, newline = request.param
    edge = "-" * 5
    header = edge + "BEGIN PRIVATE KEY" + edge
    footer = edge + "END PRIVATE KEY" + edge
    body = "SYNTHETIC_PRIVATE_BODY_CONTROL_572"
    block = newline.join((header, body, footer))
    truncated = newline.join((header, body, "withhold all trailing text"))
    prefix, suffix, between = "public prefix ", " public suffix", " between blocks "
    marker = "[REDACTED]"
    reasons = {
        "ordinary": (
            "Synthetic ordinary acknowledgement",
            "Synthetic ordinary acknowledgement",
        ),
        "complete": (prefix + block + suffix, prefix + marker + suffix),
        "unterminated": (prefix + truncated, prefix + marker),
        "adjacent-complete": (
            prefix + block * 2 + suffix,
            prefix + marker * 2 + suffix,
        ),
        "multiple-complete": (
            prefix + block + between + block + suffix,
            prefix + marker + between + marker + suffix,
        ),
        "complete-then-unterminated": (
            prefix + block + between + truncated,
            prefix + marker + between + marker,
        ),
        "adjacent-unterminated": (
            prefix + header * 3 + newline + body,
            prefix + marker,
        ),
    }
    reason, expected = reasons[kind]
    root, source, _vendor = ingest_repo
    target = source / "skills/helper/example.txt"
    target.write_bytes(b"Synthetic documentation\nAKIA" + b"A" * 16)
    path = root / "vendors.yaml"
    policy = yaml.safe_load(path.read_text())
    policy["vendors"][0]["ingestAllow"] = [
        {
            "path": "skills/helper/example.txt",
            "rule": "aws-access-key-id",
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "reason": reason,
        }
    ]
    path.write_text(yaml.safe_dump(policy))
    return expected


def configure_metadata_reason(*, root: Path, source: Path, kind: str) -> None:
    """Set a small acknowledgement or overflow one real generated metadata file.

    Args:
        root: Synthetic author repository.
        source: Synthetic vendor snapshot.
        kind: Small baseline, oversized coverage, or lock-only overflow.
    """
    target = source / "skills/helper/example.txt"
    target.write_bytes(b"Synthetic documentation\nAKIA" + b"A" * 16)
    reason = (
        "Ordinary acknowledgement "
        + {
            "small": "baseline",
            "coverage": "x" * (5 * 1024 * 1024),
            "lock": "x" * (5 * 1024 * 1024 - 1800),
        }[kind]
    )
    path = root / "vendors.yaml"
    document = yaml.safe_load(path.read_text())
    document["vendors"][0]["ingestAllow"] = [
        {
            "path": "skills/helper/example.txt",
            "rule": "aws-access-key-id",
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "reason": reason,
        }
    ]
    path.write_text(yaml.safe_dump(document))


@pytest.fixture
def google_acknowledgement(ingest_repo: tuple[Path, Path, Vendor]) -> str:
    """Acknowledge a synthetic trailing-hyphen key with the value in its reason.

    Args:
        ingest_repo: Synthetic author and vendor roots.

    Returns:
        Synthetic value which must stay out of all public output.
    """
    root, source, _ = ingest_repo
    sample = "AIza" + "A" * 34 + "-"
    target = source / "skills/helper/example.txt"
    target.write_text("Synthetic documentation\n" + sample + "\n")
    path = root / "vendors.yaml"
    document = yaml.safe_load(path.read_text())
    document["vendors"][0]["ingestAllow"] = [
        {
            "path": "skills/helper/example.txt",
            "rule": "google-api-key",
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "reason": "Synthetic example " + sample,
        }
    ]
    path.write_text(yaml.safe_dump(document))
    return sample


@pytest.fixture(params=["resource", "capability"])
def rejected_inventory(
    inventory_repo: tuple[Path, Path],
    request: pytest.FixtureRequest,
) -> tuple[Path, Path, str, str]:
    """Declare valid independent payloads alongside a rejected required payload.

    Args:
        inventory_repo: Offline consumer/vendor inputs with a network guard.
        request: Rejected resource or capability.

    Returns:
        Consumer, vendor, rejected identity and its requirer identity.
    """
    from ai_skills_engine.manifest.edit import dump_document

    root, source = inventory_repo
    (source / "valid.txt").write_text("Safe independent resource\n")
    (source / "bad.md").write_bytes(b"AKIA" + b"A" * 16 + b"\n")
    (source / "skills/help/SKILL.md").write_text(
        "---\nname: helper\ndescription: Safe independent skill.\n---\n"
    )
    requiring = source / "skills/requirer"
    requiring.mkdir()
    (requiring / "SKILL.md").write_text(
        "---\nname: requirer\ndescription: Safe requirer.\n---\n"
    )
    kind = request.param
    bad = (
        "upstream/tools:"
        + ("resource" if kind == "resource" else "instruction")
        + "/bad"
    )
    requirer = "upstream/tools:skill/requirer"
    capabilities = [
        {
            "id": "good",
            "path": "skills/help",
            "resources": ["upstream/tools:resource/valid"],
        },
        {
            "id": "requirer",
            "path": "skills/requirer",
            "resources" if kind == "resource" else "requires": [bad],
        },
    ]
    resources = [{"id": "valid", "path": "valid.txt"}]
    if kind == "resource":
        resources.append({"id": "bad", "path": "bad.md"})
    else:
        capabilities.append({"id": "bad", "path": "bad.md", "role": "instruction"})
    (source / "ai-skills.yaml").write_text(
        dump_document(
            {
                "apiVersion": "ai-skills.dev/v1",
                "publisher": {"id": "upstream"},
                "packages": [
                    {
                        "id": "tools",
                        "capabilities": capabilities,
                        "resources": resources,
                    }
                ],
            }
        )
    )
    (root / "ai-skills.yaml").write_text(
        dump_document(
            {
                "apiVersion": "ai-skills.dev/v1",
                "publisher": {"id": "fixture"},
                "vendors": [
                    {"id": "vendor", "repo": "upstream/tools", "sha": "a" * 40}
                ],
                "exports": ["upstream/tools"],
            }
        )
    )
    return root, source, bad, requirer
