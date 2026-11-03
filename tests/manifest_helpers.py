"""Offline regression fixtures scoped to manifest authoring and vendor pin tests."""

import shutil
import subprocess  # nosec B404 - bounded local lint process, no shell
from collections.abc import Callable
from pathlib import Path

import pytest
from assertpy import assert_that

from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"

PUBLICATION_SELECTION_CONTROLS = [
    ("baseline", 0),
    ("exact", 0),
    ("publisher-wildcard", 0),
    ("package-prefix-wildcard", 0),
    ("mixed", 0),
    ("empty", 1),
    ("capability", 1),
    ("capability-wildcard", 1),
    ("enumerated-capabilities", 1),
    ("unmatched-package", 1),
    ("exclusion", 1),
]


def configure_publication_selection(*, root: Path, owner: str, control: str) -> None:
    """Prepare real canonical publication with whole-package or narrowing includes.

    Args:
        root: Isolated author tree with real first-party skill payloads.
        owner: Local package or mapped multi-package vendor declaration.
        control: Include/exclude behavior to exercise through real publication.
    """
    data = read_document(SCRIPTS_DIR.parent / "ai-skills.yaml")
    if owner == "local":
        declaration = data["packages"][0]
        publisher = data["publisher"]["id"]
        packages = [declaration]
        names = [item["id"] for item in declaration["capabilities"]]
    else:
        declaration = next(v for v in data["vendors"] if v["id"] == "anthropics")
        publisher = declaration["id"]
        packages = declaration["mapping"]["packages"]
        names = packages[0]["skills"]
    qualified = [f"{publisher}/{package['id']}" for package in packages]
    capability = f"{qualified[0]}:skill/{names[0]}"
    includes = {
        "exact": qualified,
        "publisher-wildcard": [f"{publisher}/*"],
        "package-prefix-wildcard": [f"{item[:-1]}*" for item in qualified],
        "mixed": [capability, f"{publisher}/*"],
        "empty": [],
        "capability": [capability],
        "capability-wildcard": [f"{item}:skill/*" for item in qualified],
        "enumerated-capabilities": (
            [f"{qualified[0]}:skill/{name}" for name in names]
            if owner == "local"
            else [
                f"{publisher}/{package['id']}:skill/{name}"
                for package in packages
                for name in package["skills"]
            ]
        ),
        "unmatched-package": [f"{publisher}/other-*"],
        "exclusion": [f"{publisher}/*"],
    }
    if control != "baseline":
        declaration["include"] = includes[control]
        declaration["exclude"] = [capability] if control == "exclusion" else []
    (root / "ai-skills.yaml").write_text(dump_document(data))


@pytest.fixture
def author_skills(tmp_path: Path) -> None:
    """Supply the actual first-party payloads declared by publication fixtures."""
    shutil.copytree(src=SCRIPTS_DIR.parent / "skills", dst=tmp_path / "skills")


@pytest.fixture
def check_yaml() -> Callable[[Path], None]:
    """Check generated YAML with the same configuration used by Lintro.

    Returns:
        Assertion helper invoking the installed yamllint tool without acquisition.
    """

    def check(path: Path) -> None:
        """Lint one real author output using repository rules."""
        executable = shutil.which("yamllint")
        if executable is None:
            pytest.fail("yamllint is required to check generated registry layout")
        result = subprocess.run(  # nosec B603 - fixed local tool argv, no shell
            [executable, "-c", str(SCRIPTS_DIR.parent / ".yamllint"), str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert_that(result.returncode).described_as(
            result.stdout + result.stderr
        ).is_zero()

    return check
