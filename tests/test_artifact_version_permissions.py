"""Public regressions for project versions and complete permission expressions."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from artifact_helpers import bake_fixture, index_at
from assertpy import assert_that

from ai_skills_engine import cli
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.semver_advice import recommend_semver

pytest_plugins = ["artifact_helpers"]

PERMISSION_CHANGES = [
    pytest.param(
        "Bash(git status), Bash(npm test)",
        "Bash(git test), Bash(npm status)",
        "major",
        "major",
        id="recombined",
    ),
    pytest.param("Read, Write", "Read, Write", "none", "none", id="identical"),
    pytest.param("Read, Write", "Write Read", "patch", "patch", id="reordered"),
    pytest.param("Read", "Read, Write", "major", "patch", id="added"),
    pytest.param("Read, Write", "Read", "patch", "major", id="removed"),
    pytest.param(["Read"], ["Read", "Write"], "major", "patch", id="list-added"),
    pytest.param(["Read", "Write"], ["Read"], "patch", "major", id="list-removed"),
    pytest.param(
        ["Bash(git status)", "Bash(npm test)"],
        ["Bash(git test)", "Bash(npm status)"],
        "major",
        "major",
        id="list-recombined",
    ),
    pytest.param(
        "Bash(git status), Bash(npm test)",
        "Bash(git status)",
        "patch",
        "major",
        id="command-removed",
    ),
    pytest.param(
        "Bash(git status), Bash(npm test)",
        ["Bash(npm test)", "Bash(git status)"],
        "patch",
        "patch",
        id="string-to-list",
    ),
    pytest.param(
        'Bash(printf "hello, ) world"), Read',
        'Read Bash(printf "hello, ) world")',
        "patch",
        "patch",
        id="quoted-delimiters",
    ),
    pytest.param(
        "Bash(printf 'a,(b)'), Read",
        "Bash(printf 'a,(b)')",
        "patch",
        "major",
        id="single-quoted-delimiters",
    ),
    pytest.param(
        r'Bash(printf "a\"),b"), Read',
        r'Bash(printf "a\"),b")',
        "patch",
        "major",
        id="escaped-quote",
    ),
    pytest.param(
        "Bash(git status), Read",
        "Bash(git  status), Read",
        "major",
        "major",
        id="internal-whitespace",
    ),
    pytest.param(
        "Bash(printf a,b), Read",
        "Bash(printf b,a), Read",
        "major",
        "major",
        id="internal-comma",
    ),
    pytest.param("Read, Write", "  Write,  Read  ", "patch", "patch", id="spacing"),
    pytest.param("Bash(git status", "Bash(git test", "major", "major", id="unclosed"),
    pytest.param("Read", "Bash((git status))", "major", "major", id="nested"),
    pytest.param("Read", {"unknown": "Write"}, "major", "major", id="mapping"),
    pytest.param(["Read", 1], ["Read"], "major", "major", id="nonstring-list"),
    pytest.param("Read + Write", "Write + Read", "major", "major", id="unknown"),
    pytest.param("Bash(unclosed", "Bash(unclosed", "none", "none", id="same-unknown"),
    pytest.param(None, "Read", "patch", "patch", id="restrict-unbounded"),
    pytest.param("Read", None, "major", "major", id="remove-declaration"),
]


@pytest.mark.parametrize("manifest_version", [None, "2.3.4"], ids=["local", "manifest"])
@pytest.mark.parametrize(
    "pyproject",
    [
        None,
        '[project]\nname="fixture"\nversion="1.2.3"\n',
        "[tool.fixture]\nenabled=true\n",
        (
            '[project]\nname="fixture"\ndynamic=["version"]\n'
            '[build-system]\nrequires=[]\nbuild-backend="must_never_execute"\n'
        ),
    ],
    ids=["absent", "static", "tool-only", "dynamic"],
)
def test_public_project_version_fallback(
    artifact_repo: Path, manifest_version: str | None, pyproject: str | None
) -> None:
    """Build/check use static versions first, then manifest/local without execution."""
    manifest = artifact_repo / "ai-skills.yaml"
    document = read_document(manifest)
    document.pop("x-version", None)
    if manifest_version is not None:
        document["x-version"] = manifest_version
    manifest.write_text(dump_document(document))
    if pyproject is not None:
        (artifact_repo / "pyproject.toml").write_text(pyproject)
    args = ["--repo-root", str(artifact_repo)]
    assert_that(cli.main([*args, "lock"])).is_zero()
    assert_that(cli.main([*args, "build"])).is_zero()
    expected = (
        "1.2.3"
        if pyproject and 'version="1.2.3"' in pyproject
        else manifest_version or "0.0.0-local"
    )
    index = index_at(artifact_repo / "dist/artifacts")
    assert_that(index["packages"][0]["version"]).is_equal_to(expected)
    reviewed = (artifact_repo / "ai-skills.lock").read_bytes()
    for command in (["lock", "--check"], ["lock", "--check", "--inputs-only"]):
        assert_that(cli.main([*args, *command])).is_zero()
    assert_that((artifact_repo / "ai-skills.lock").read_bytes()).is_equal_to(reviewed)


def test_public_malformed_project_fails_closed(
    artifact_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Malformed TOML never falls back or replaces the reviewed resolution lock."""
    args = ["--repo-root", str(artifact_repo)]
    assert_that(cli.main([*args, "lock"])).is_zero()
    reviewed = (artifact_repo / "ai-skills.lock").read_bytes()
    (artifact_repo / "pyproject.toml").write_text('[project\nversion="1.2.3"')
    capsys.readouterr()
    assert_that(cli.main([*args, "lock"])).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("lock:", "table declaration")
    for command in (["lock", "--check"], ["build"]):
        assert_that(cli.main([*args, *command])).is_equal_to(1)
    assert_that((artifact_repo / "ai-skills.lock").read_bytes()).is_equal_to(reviewed)


@pytest.mark.parametrize("key", ["allowed-tools", "tools", "disallowedTools"])
@pytest.mark.parametrize(
    ("old", "new", "allow_level", "deny_level"), PERMISSION_CHANGES
)
def test_complete_permission_comparison(
    key: str, old: object, new: object, allow_level: str, deny_level: str
) -> None:
    """Whole permissions are compared; uncertain changes receive major advice."""

    def index(value: object) -> dict[str, Any]:
        """Represent a resolved permission declaration for the focused diff."""
        return {
            "packages": [
                {
                    "capabilities": [
                        {
                            "id": "fixture/tools:skill/start",
                            "requires": [],
                            "hostAttributes": (
                                []
                                if value is None
                                else [
                                    {
                                        "key": key,
                                        "semantics": "permission",
                                        "value": value,
                                    }
                                ]
                            ),
                        }
                    ]
                }
            ]
        }

    advice = recommend_semver(index(old), index(new))
    expected = deny_level if key == "disallowedTools" else allow_level
    assert_that(advice.level).is_equal_to(expected)
    if expected == "major":
        assert_that("\n".join(advice.reasons)).contains("Widened " + key)


@pytest.mark.parametrize("key", ["allowed-tools", "tools", "disallowedTools"])
@pytest.mark.parametrize(
    ("old", "new", "allow_level", "deny_level"), PERMISSION_CHANGES[:5]
)
def test_public_resolved_permission_advice(
    artifact_repo: Path,
    tmp_path: Path,
    key: str,
    old: object,
    new: object,
    allow_level: str,
    deny_level: str,
) -> None:
    """Resolved inventory and artifact metadata reach the public advisor intact."""
    source = artifact_repo / "skills/start/SKILL.md"
    original = source.read_text()
    indexes = []
    for name, value in (("before", old), ("after", new)):
        declaration = yaml.safe_dump({key: value}, default_flow_style=False)
        source.write_text(
            original.replace("\n---\n# Start", "\n" + declaration + "---\n# Start")
        )
        destination = tmp_path / name
        bake_fixture(root=artifact_repo, destination=destination)
        index = index_at(destination)
        capability = next(
            item
            for item in index["packages"][0]["capabilities"]
            if item["id"] == "fixture/tools:skill/start"
        )
        attribute = next(
            item for item in capability["hostAttributes"] if item["key"] == key
        )
        assert_that(attribute["value"]).is_equal_to(value)
        assert_that(attribute["semantics"]).is_equal_to("permission")
        indexes.append(index)
    result = recommend_semver(*indexes)
    assert_that(result.level).is_equal_to(
        deny_level if key == "disallowedTools" else allow_level
    )
