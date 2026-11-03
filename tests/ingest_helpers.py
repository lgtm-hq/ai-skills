"""Synthetic vendor snapshots shared by ingestion boundary tests."""

import hashlib
from pathlib import Path

import pytest
import yaml

from ai_skills_engine.registry.registry import load_registry
from ai_skills_engine.registry.vendor import Vendor


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
