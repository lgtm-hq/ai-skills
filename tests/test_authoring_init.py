"""``init`` scaffolds a valid manifest and a SHA-pinned caller, never overwriting."""

import shutil
from pathlib import Path

import pytest
import yaml
from assertpy import assert_that
from authoring_helpers import run_cli

from ai_skills_engine.artifact import installed_engine_version
from ai_skills_engine.commands import init
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.registry.vendor import Vendor

pytest_plugins = ["authoring_helpers"]

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/vendors"
SHA = "abcdef0123456789abcdef0123456789abcdef01"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Copy the manifestless fixture vendor as a repository to initialize.

    Args:
        tmp_path: Test directory.

    Returns:
        Repository root without ``ai-skills.yaml``.
    """
    root = tmp_path / "tools-repo"
    shutil.copytree(FIXTURES / "manifestless", root)
    return root


def _run(*arguments: str) -> tuple[int, str, str]:
    """Invoke the public CLI.

    Args:
        arguments: Command line.

    Returns:
        Status, stdout and stderr.
    """
    result: tuple[int, str, str] = run_cli(*arguments)
    return result


def test_init_manifest_passes_validate_and_second_run_is_noop(repo: Path) -> None:
    """The scaffold validates strictly; rerunning reports and keeps both files."""
    status, output, _ = _run("init", "--repo-root", str(repo), "--engine-ref", SHA)
    assert_that(status).is_zero()
    assert_that(output).contains(
        "wrote ai-skills.yaml", "wrote .github/workflows/ai-skills.yml"
    )
    document = read_document(repo / "ai-skills.yaml")
    assert_that(document["packages"]).is_length(1)
    package = document["packages"][0]
    assert_that(package["id"]).is_equal_to("fixture-tools")
    assert_that(package["capabilities"]).is_equal_to(
        [
            {"id": "helper", "path": "agents/helper.md", "role": "specialist"},
            {"id": "delta", "path": "skills/delta"},
            {"id": "epsilon", "path": "skills/epsilon"},
        ]
    )
    assert_that(document["exports"]).is_equal_to(["fixture-tools"])
    validated, report, _ = _run("validate", "--repo-root", str(repo), "--strict")
    assert_that(validated).described_as(report).is_zero()
    assert_that(report).contains("validate: passed")
    before = {
        path: path.read_bytes()
        for path in (repo / "ai-skills.yaml", repo / init.CALLER_WORKFLOW)
    }
    again, output, _ = _run("init", "--repo-root", str(repo))
    assert_that(again).is_zero()
    assert_that(output).contains(
        "ai-skills.yaml already exists; left unchanged",
        f"{init.CALLER_WORKFLOW} already exists; left unchanged",
    )
    assert_that({path: path.read_bytes() for path in before}).is_equal_to(before)


def test_dry_run_prints_without_writing(repo: Path) -> None:
    """``--dry-run`` renders both files and creates nothing."""
    status, output, _ = _run(
        "init", "--repo-root", str(repo), "--engine-ref", SHA, "--dry-run"
    )
    assert_that(status).is_zero()
    assert_that(output).contains(
        "would write ai-skills.yaml", "apiVersion: ai-skills.dev/v1", SHA
    )
    assert_that((repo / "ai-skills.yaml").exists()).is_false()
    assert_that((repo / ".github").exists()).is_false()


def test_existing_manifest_is_never_overwritten(repo: Path) -> None:
    """An existing manifest keeps its bytes; only the missing caller is created."""
    (repo / "ai-skills.yaml").write_text("hand-written: true\n")
    status, output, _ = _run("init", "--repo-root", str(repo), "--engine-ref", SHA)
    assert_that(status).is_zero()
    assert_that(output).contains("ai-skills.yaml already exists; left unchanged")
    assert_that((repo / "ai-skills.yaml").read_text()).is_equal_to(
        "hand-written: true\n"
    )
    assert_that((repo / init.CALLER_WORKFLOW).is_file()).is_true()


def test_caller_pins_reusable_workflow_and_engine_by_full_sha(repo: Path) -> None:
    """Both pins are the same 40-hex SHA, and the inputs exist on the callee."""
    assert_that(
        _run("init", "--repo-root", str(repo), "--engine-ref", SHA)[0]
    ).is_zero()
    caller = yaml.safe_load((repo / init.CALLER_WORKFLOW).read_text())
    job = caller["jobs"]["validate"]
    assert_that(job["uses"]).is_equal_to(
        f"lgtm-hq/ai-skills/{init.REUSABLE_WORKFLOW}@{SHA}"
    )
    assert_that(job["with"]).is_equal_to(
        {"engine-ref": SHA, "manifest-path": "ai-skills.yaml", "strict": True}
    )
    assert_that(job["with"]).does_not_contain_key("terminology")
    assert_that(caller["on"]).is_equal_to(
        {"pull_request": None, "merge_group": None, "push": {"branches": ["main"]}}
    )
    assert_that(caller["permissions"]).is_equal_to({"contents": "read"})
    callee = yaml.safe_load((ROOT / init.REUSABLE_WORKFLOW).read_text())
    inputs = callee["on"]["workflow_call"]["inputs"]
    assert_that(inputs).contains_key(*job["with"])
    assert_that(inputs["engine-ref"]["required"]).is_true()


@pytest.mark.parametrize("ref", ["abc123", "A" * 40, SHA + "0", "main"])
def test_engine_ref_must_be_full_lowercase_sha(repo: Path, ref: str) -> None:
    """Short, uppercase, long or symbolic refs are refused before writing."""
    status, _, error = _run("init", "--repo-root", str(repo), "--engine-ref", ref)
    assert_that(status).is_equal_to(1)
    assert_that(error).contains("full 40-hex commit SHA")
    assert_that((repo / "ai-skills.yaml").exists()).is_false()


def test_default_engine_ref_resolves_this_release_tag(
    repo: Path, forge: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``--engine-ref`` the release tag resolves through the repin resolver."""
    del forge
    from ai_skills_engine.vendors import repin

    requests: list[tuple[str, str | None]] = []

    def resolve(*, vendor: Vendor) -> str:
        requests.append((vendor.repo, vendor.display_ref))
        return SHA

    monkeypatch.setattr(repin, "resolve_upstream_sha", resolve)
    monkeypatch.setattr(init, "installed_engine_version", lambda: "1.2.3")
    assert_that(_run("init", "--repo-root", str(repo))[0]).is_zero()
    assert_that(requests).is_equal_to([("lgtm-hq/ai-skills", "v1.2.3")])
    assert_that((repo / init.CALLER_WORKFLOW).read_text()).contains(
        f"@{SHA} # ai-skills 1.2.3"
    )
    monkeypatch.setattr(init, "installed_engine_version", lambda: "0.0.0-dev")
    (repo / init.CALLER_WORKFLOW).unlink()
    status, _, error = _run("init", "--repo-root", str(repo))
    assert_that(status).is_equal_to(1)
    assert_that(error).contains("has no release tag; pass --engine-ref SHA")


def test_origin_remote_and_explicit_identity(repo: Path) -> None:
    """The publisher comes from ``.git/config`` text, overridable by flags."""
    (repo / ".git").mkdir()
    (repo / ".git/config").write_text(
        '[remote "origin"]\n\turl = git@github.com:Example-Org/Tools_Repo.git\n'
    )
    proposal, _ = init.propose(root=repo, publisher=None, repo=None)
    assert_that(proposal["publisher"]).is_equal_to(
        {"id": "example-org", "repo": "Example-Org/Tools_Repo"}
    )
    explicit, _ = init.propose(root=repo, publisher="acme", repo="acme/skills")
    assert_that(explicit["publisher"]).is_equal_to(
        {"id": "acme", "repo": "acme/skills"}
    )


@pytest.mark.parametrize("relative", [True, False], ids=["relative", "absolute"])
def test_origin_remote_is_read_from_a_linked_worktree(
    repo: Path, tmp_path: Path, relative: bool
) -> None:
    """A worktree's ``.git`` file leads to the shared config holding the remote."""
    common = tmp_path / "main/.git"
    private = common / "worktrees/tools-repo"
    private.mkdir(parents=True)
    (private / "commondir").write_text("../..\n")
    (common / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/example-org/tools.git\n'
    )
    target = Path("../main/.git/worktrees/tools-repo") if relative else private
    (repo / ".git").write_text(f"gitdir: {target}\n")
    proposal, _ = init.propose(root=repo, publisher=None, repo=None)
    assert_that(proposal["publisher"]).is_equal_to(
        {"id": "example-org", "repo": "example-org/tools"}
    )


def test_invalid_names_are_reported_and_empty_repositories_refused(
    tmp_path: Path,
) -> None:
    """Non-kebab names are skipped with a note; nothing publishable is an error."""
    root = tmp_path / "plain"
    (root / "skills/Bad_Name").mkdir(parents=True)
    (root / "skills/Bad_Name/SKILL.md").write_text("---\nname: x\n---\n")
    (root / "skills/good").mkdir()
    (root / "skills/good/SKILL.md").write_text("---\nname: good\n---\n")
    proposal, notes = init.propose(root=root, publisher="plain", repo=None)
    assert_that(proposal["packages"][0]["capabilities"]).is_equal_to(
        [{"id": "good", "path": "skills/good"}]
    )
    assert_that(notes).is_equal_to(
        ["skipped skills/Bad_Name: 'Bad_Name' is not a kebab-case ID"]
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    status, _, error = _run(
        "init", "--repo-root", str(empty), "--engine-ref", SHA, "--publisher", "x"
    )
    assert_that(status).is_equal_to(1)
    assert_that(error).contains("nothing to publish")
    assert_that(installed_engine_version()).is_not_empty()
