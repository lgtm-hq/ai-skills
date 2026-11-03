"""Synthetic vendor snapshots shared by ingestion boundary tests."""

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
