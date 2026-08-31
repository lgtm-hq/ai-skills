"""Tests for vendor re-pin summaries, CLI, and the scheduled workflow."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import bake_vendor_indexes
import bake_vendor_plugins
import pytest
import repin_vendor
import yaml
from assertpy import assert_that
from vendor_registry.registry import load_registry
from vendor_registry.vendor import Vendor
from vendor_registry.vendor_repin_diff import diff_snapshots, render_json
from vendor_registry.vendor_repin_snapshot import VendorRepinSnapshot

_EXISTING_SHA = "0123456789abcdef0123456789abcdef01234567"
_NEW_SHA = "89abcdef0123456789abcdef0123456789abcdef"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHA_USES = re.compile(
    r"uses:\s+\S+@(?P<ref>[0-9a-f]{40})\s+#",
)
_TAG_USES = re.compile(
    r"uses:\s+\S+@v\d",
)

_PLUGINS_YAML = (
    "plugins:\n"
    "      - id: example-plugin\n"
    "        description: Example vendor plugin.\n"
    "        skillsRoot: skills\n"
    '        skills: "*"\n'
)


def _fixed_new_sha(_vendor: object) -> str:
    """Return the post-re-pin SHA, ignoring the vendor record.

    Args:
        _vendor: Registry vendor (unused).

    Returns:
        The new pin SHA.
    """
    del _vendor
    return _NEW_SHA


def _fixed_new_sha_kw(*, vendor: Vendor) -> str:
    """Return the post-re-pin SHA for keyword-only stubs.

    Args:
        vendor: Registry vendor (unused).

    Returns:
        The new pin SHA.
    """
    del vendor
    return _NEW_SHA


def _current_sha_kw(*, vendor: Vendor) -> str:
    """Return the vendor's current pin SHA.

    Args:
        vendor: Registry vendor.

    Returns:
        The existing pin SHA.
    """
    return str(vendor.sha)


def _write_skill(*, directory: Path, name: str, body: str | None = None) -> None:
    """Write a SKILL.md into ``directory``.

    Args:
        directory: Skill directory to create.
        name: Frontmatter ``name`` value.
        body: Optional body appended after the frontmatter.
    """
    directory.mkdir(parents=True, exist_ok=True)
    extra = f"{body}\n" if body is not None else ""
    directory.joinpath("SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} skill.\n---\n{extra}",
        encoding="utf-8",
    )


def _write_before_tree(*, dest: Path) -> None:
    """Populate the pre-re-pin vendor tree.

    Args:
        dest: Unpacked vendor destination.
    """
    dest.mkdir(parents=True, exist_ok=True)
    _write_skill(directory=dest / "skills" / "alpha", name="alpha", body="alpha-body")
    _write_skill(directory=dest / "skills" / "beta", name="beta", body="beta-body")
    _write_skill(
        directory=dest / "template" / "placeholder",
        name="placeholder",
        body="skip-me",
    )


def _write_after_tree(*, dest: Path) -> None:
    """Populate the post-re-pin vendor tree.

    ``gamma`` keeps ``beta``'s body so the diff reports a rename.
    ``delta`` is new. The template skill is gone (coverage delta).

    Args:
        dest: Unpacked vendor destination.
    """
    dest.mkdir(parents=True, exist_ok=True)
    _write_skill(directory=dest / "skills" / "alpha", name="alpha", body="alpha-body")
    _write_skill(directory=dest / "skills" / "gamma", name="gamma", body="beta-body")
    _write_skill(directory=dest / "skills" / "delta", name="delta", body="delta-body")


def _write_collision_tree(*, dest: Path) -> None:
    """Populate a tree that collides with first-party ``skills/alpha``.

    Args:
        dest: Unpacked vendor destination.
    """
    dest.mkdir(parents=True, exist_ok=True)
    _write_skill(directory=dest / "skills" / "alpha", name="alpha", body="alpha-body")
    _write_skill(directory=dest / "skills" / "teach", name="teach", body="teach-body")


def _write_registry(*, repo_root: Path) -> None:
    """Write vendors.yaml, bundles.yaml, and a stub npm package.

    Args:
        repo_root: Isolated repository root.
    """
    repo_root.joinpath("vendors.yaml").write_text(
        "---\n"
        "vendors:\n"
        "  - id: example-vendor\n"
        "    repo: owner/example\n"
        f'    sha: "{_EXISTING_SHA}"\n'
        "    displayRef: latest\n"
        "    skillRoots:\n"
        "      - skills\n"
        f"    {_PLUGINS_YAML}"
        "    license: MIT\n"
        "    homepage: https://github.com/owner/example\n",
        encoding="utf-8",
    )
    repo_root.joinpath("bundles.yaml").write_text(
        "---\n"
        "groups:\n"
        "  git-pr:\n"
        "    id: git-pr\n"
        "    name: Git & PR Workflow\n"
        "    description: First-party plugin.\n"
        "    skills:\n"
        "      - branch\n",
        encoding="utf-8",
    )
    package_root = repo_root / "npm" / "ai-skills"
    package_root.mkdir(parents=True)
    package_root.joinpath("package.json").write_text(
        '{\n  "name": "@lgtm-hq/ai-skills",\n  "version": "0.0.0-dev"\n}\n',
        encoding="utf-8",
    )


def _snapshot(
    *,
    sha: str,
    names: frozenset[str],
    skipped: tuple[str, ...],
    ingested: int,
    collisions: tuple[str, ...] = (),
    digests: tuple[tuple[str, str], ...] = (),
) -> VendorRepinSnapshot:
    """Build a snapshot for pure diff tests.

    Args:
        sha: Pin SHA.
        names: Explode names.
        skipped: Skipped SKILL.md paths.
        ingested: Ingested count.
        collisions: Collision lines.
        digests: Explode name → digest pairs.

    Returns:
        Frozen snapshot.
    """
    return VendorRepinSnapshot(
        vendor_id="example-vendor",
        sha=sha,
        explode_names=names,
        skipped=skipped,
        ingested_count=ingested,
        collisions=collisions,
        skill_digests=digests,
    )


@pytest.fixture
def tree_kind() -> dict[str, str]:
    """Mutable after-pin tree selector shared with the fetch stubs.

    Returns:
        Mapping with a ``kind`` of ``before``, ``after``, or ``collision``.
    """
    return {"kind": "before"}


@pytest.fixture
def repo_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tree_kind: dict[str, str],
) -> Path:
    """Isolated repo with plugin slices and a stubbed GitHub tree fetch.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Fixture used to stub fetches.
        tree_kind: Selector for the post-pin vendor tree.

    Returns:
        Repository root.
    """

    def fake_index_tree(*, vendor: object) -> list[str]:
        sha = getattr(vendor, "sha", "")
        if sha == _EXISTING_SHA:
            return [
                "skills/alpha/SKILL.md",
                "skills/beta/SKILL.md",
                "template/placeholder/SKILL.md",
            ]
        if tree_kind["kind"] == "collision":
            return ["skills/alpha/SKILL.md", "skills/teach/SKILL.md"]
        return [
            "skills/alpha/SKILL.md",
            "skills/gamma/SKILL.md",
            "skills/delta/SKILL.md",
        ]

    def fake_plugin_tree(*, vendor: object, dest: Path) -> None:
        sha = getattr(vendor, "sha", "")
        if sha == _EXISTING_SHA:
            _write_before_tree(dest=dest)
            return
        if tree_kind["kind"] == "collision":
            _write_collision_tree(dest=dest)
            return
        _write_after_tree(dest=dest)

    monkeypatch.setattr(bake_vendor_indexes, "_fetch_tree_paths", fake_index_tree)
    monkeypatch.setattr(bake_vendor_plugins, "_fetch_vendor_tree", fake_plugin_tree)
    _write_registry(repo_root=tmp_path)
    return tmp_path


def test_diff_reports_added_removed_and_renamed() -> None:
    """Digest-matched explode names are renamed, not added+removed."""
    before = _snapshot(
        sha=_EXISTING_SHA,
        names=frozenset({"alpha", "beta"}),
        skipped=("template/placeholder/SKILL.md",),
        ingested=2,
        digests=(("alpha", "aaa"), ("beta", "bbb")),
    )
    after = _snapshot(
        sha=_NEW_SHA,
        names=frozenset({"alpha", "gamma", "delta"}),
        skipped=(),
        ingested=3,
        digests=(("alpha", "aaa"), ("gamma", "bbb"), ("delta", "ddd")),
    )

    diff = diff_snapshots(before=before, after=after)

    assert_that(diff.unchanged).is_false()
    assert_that(diff.added_skills).is_equal_to(("delta",))
    assert_that(diff.removed_skills).is_equal_to(())
    assert_that(diff.renamed_skills).is_equal_to((("beta", "gamma"),))
    assert_that(diff.skipped_removed).is_equal_to(
        ("template/placeholder/SKILL.md",),
    )
    assert_that(diff.ingested_before).is_equal_to(2)
    assert_that(diff.ingested_after).is_equal_to(3)


def test_diff_rename_matching_is_one_to_one() -> None:
    """Duplicate SKILL.md bodies claim each old explode name at most once."""
    before = _snapshot(
        sha=_EXISTING_SHA,
        names=frozenset({"old-a", "old-b"}),
        skipped=(),
        ingested=2,
        digests=(("old-a", "same"), ("old-b", "same")),
    )
    after = _snapshot(
        sha=_NEW_SHA,
        names=frozenset({"new-a", "new-b"}),
        skipped=(),
        ingested=2,
        digests=(("new-a", "same"), ("new-b", "same")),
    )

    diff = diff_snapshots(before=before, after=after)

    assert_that(diff.renamed_skills).is_equal_to((("old-b", "new-a"),))
    assert_that(diff.added_skills).is_equal_to(("new-b",))
    assert_that(diff.removed_skills).is_equal_to(("old-a",))


def test_diff_surfaces_new_collisions() -> None:
    """Collisions present only after the bump are listed as new."""
    before = _snapshot(
        sha=_EXISTING_SHA,
        names=frozenset({"alpha"}),
        skipped=(),
        ingested=1,
    )
    after = _snapshot(
        sha=_NEW_SHA,
        names=frozenset({"alpha", "teach"}),
        skipped=(),
        ingested=2,
        collisions=("COLLIDES 'teach': first-party skills/teach vs example-plugin",),
    )

    diff = diff_snapshots(before=before, after=after)

    assert_that(diff.collisions).is_length(1)
    assert_that(diff.new_collisions).is_equal_to(diff.collisions)
    payload = json.loads(render_json(diff=diff, display_ref="latest"))
    assert_that(payload["newCollisions"]).is_equal_to(list(diff.new_collisions))


def test_repin_updates_sha_and_summarizes_skill_delta(
    repo_root: Path,
    tree_kind: dict[str, str],
) -> None:
    """A pin bump rebakes and reports added, renamed, and coverage deltas."""
    bake_vendor_plugins.bake(repo_root=repo_root)
    tree_kind["kind"] = "after"

    diff = repin_vendor.repin_vendor(
        repo_root=repo_root,
        vendor_id="example-vendor",
        resolve_sha=_fixed_new_sha,
    )

    vendor = load_registry(registry_path=repo_root / "vendors.yaml")[0]
    assert_that(vendor.sha).is_equal_to(_NEW_SHA)
    assert_that(diff.unchanged).is_false()
    assert_that(diff.added_skills).contains("delta")
    assert_that(diff.renamed_skills).contains(("beta", "gamma"))
    assert_that(diff.collisions).is_empty()
    assert_that(diff.skipped_removed).contains("template/placeholder/SKILL.md")
    package_vendors = yaml.safe_load(
        (repo_root / "npm" / "ai-skills" / "data" / "vendors.yaml").read_text(
            encoding="utf-8",
        ),
    )
    assert_that(package_vendors["vendors"][0]["sha"]).is_equal_to(_NEW_SHA)


def test_repin_is_unchanged_when_upstream_matches_pin(
    repo_root: Path,
) -> None:
    """Resolving the current SHA is a no-op."""
    bake_vendor_plugins.bake(repo_root=repo_root)

    diff = repin_vendor.repin_vendor(
        repo_root=repo_root,
        vendor_id="example-vendor",
        resolve_sha=lambda vendor: str(vendor.sha),
    )

    assert_that(diff.unchanged).is_true()
    vendor = load_registry(registry_path=repo_root / "vendors.yaml")[0]
    assert_that(vendor.sha).is_equal_to(_EXISTING_SHA)


def test_repin_keeps_pin_and_reports_unresolved_collision(
    repo_root: Path,
    tree_kind: dict[str, str],
) -> None:
    """Collisions fail closed but leave the bumped pin for a review PR."""
    first_party = repo_root / "skills" / "teach"
    _write_skill(directory=first_party, name="teach", body="first-party")
    bake_vendor_plugins.bake(repo_root=repo_root)
    tree_kind["kind"] = "collision"

    diff = repin_vendor.repin_vendor(
        repo_root=repo_root,
        vendor_id="example-vendor",
        resolve_sha=_fixed_new_sha,
    )

    vendor = load_registry(registry_path=repo_root / "vendors.yaml")[0]
    assert_that(vendor.sha).is_equal_to(_NEW_SHA)
    assert_that(diff.collisions).is_not_empty()
    assert_that(diff.new_collisions).is_not_empty()
    assert_that("".join(diff.collisions)).contains("teach")


def test_repin_restores_pin_when_index_bake_fails(
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed rebake must not leave a bumped SHA or half-written indexes."""
    bake_vendor_plugins.bake(repo_root=repo_root)

    def fail_index_bake(*, repo_root: Path) -> None:
        del repo_root
        raise RuntimeError("index bake failed")

    monkeypatch.setattr(bake_vendor_indexes, "bake", fail_index_bake)

    with pytest.raises(RuntimeError, match="index bake failed"):
        repin_vendor.repin_vendor(
            repo_root=repo_root,
            vendor_id="example-vendor",
            resolve_sha=_fixed_new_sha,
        )

    vendor = load_registry(registry_path=repo_root / "vendors.yaml")[0]
    assert_that(vendor.sha).is_equal_to(_EXISTING_SHA)


def test_main_returns_one_when_repin_introduces_collisions(
    repo_root: Path,
    tree_kind: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI exit code 1 surfaces unresolved collisions."""
    _write_skill(
        directory=repo_root / "skills" / "teach",
        name="teach",
        body="first-party",
    )
    bake_vendor_plugins.bake(repo_root=repo_root)
    tree_kind["kind"] = "collision"
    monkeypatch.setattr(
        repin_vendor,
        "resolve_upstream_sha",
        _fixed_new_sha_kw,
    )

    status = repin_vendor.main(
        ["--repo-root", str(repo_root), "--id", "example-vendor"],
    )

    assert_that(status).is_equal_to(1)
    vendor = load_registry(registry_path=repo_root / "vendors.yaml")[0]
    assert_that(vendor.sha).is_equal_to(_NEW_SHA)


def test_main_list_json_and_summary_path(
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--list-json`` prints ids; ``--summary-path`` writes Markdown."""
    listed = repin_vendor.main(
        ["--repo-root", str(repo_root), "--list-json"],
    )
    captured = capsys.readouterr()
    assert_that(listed).is_zero()
    assert_that(json.loads(captured.out)).is_equal_to(["example-vendor"])

    bake_vendor_plugins.bake(repo_root=repo_root)
    monkeypatch.setattr(
        repin_vendor,
        "resolve_upstream_sha",
        _current_sha_kw,
    )
    summary = tmp_path / "summary.md"
    status = repin_vendor.main(
        [
            "--repo-root",
            str(repo_root),
            "--id",
            "example-vendor",
            "--summary-path",
            str(summary),
        ],
    )
    assert_that(status).is_zero()
    assert_that(summary.read_text(encoding="utf-8")).contains("already at")


def test_resolve_upstream_sha_uses_default_branch_for_latest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``latest`` tracks the GitHub default branch HEAD."""
    vendor = load_registry(registry_path=_REPO_ROOT / "vendors.yaml")[0]

    def fake_get(*, host: str, path: str, headers: dict[str, str]) -> bytes:
        del host, headers
        if path.endswith("/commits/main"):
            return json.dumps({"sha": _NEW_SHA}).encode("utf-8")
        if path == f"/repos/{vendor.repo}":
            return json.dumps({"default_branch": "main"}).encode("utf-8")
        raise AssertionError(path)

    monkeypatch.setattr(bake_vendor_plugins, "_http_get_bytes", fake_get)
    sha = repin_vendor.resolve_upstream_sha(vendor=vendor)
    assert_that(sha).is_equal_to(_NEW_SHA)


def test_resolve_upstream_sha_uses_display_ref_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tag ``displayRef`` is resolved as that git ref."""
    vendors = load_registry(registry_path=_REPO_ROOT / "vendors.yaml")
    vendor = vendors[0]
    tagged = replace(vendor, display_ref="v1.2.3")

    def fake_get(*, host: str, path: str, headers: dict[str, str]) -> bytes:
        del host, headers
        assert_that(path).contains("/commits/v1.2.3")
        return json.dumps({"sha": _NEW_SHA}).encode("utf-8")

    monkeypatch.setattr(bake_vendor_plugins, "_http_get_bytes", fake_get)
    sha = repin_vendor.resolve_upstream_sha(vendor=tagged)
    assert_that(sha).is_equal_to(_NEW_SHA)


def test_resolve_upstream_sha_percent_encodes_slash_in_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slash-containing ``displayRef`` values are encoded in the commits URL."""
    vendors = load_registry(registry_path=_REPO_ROOT / "vendors.yaml")
    vendor = vendors[0]
    tagged = replace(vendor, display_ref="heads/feature/foo")

    def fake_get(*, host: str, path: str, headers: dict[str, str]) -> bytes:
        del host, headers
        assert_that(path).contains("/commits/heads%2Ffeature%2Ffoo")
        return json.dumps({"sha": _NEW_SHA}).encode("utf-8")

    monkeypatch.setattr(bake_vendor_plugins, "_http_get_bytes", fake_get)
    sha = repin_vendor.resolve_upstream_sha(vendor=tagged)
    assert_that(sha).is_equal_to(_NEW_SHA)


def test_vendor_repin_workflow_is_sha_pinned_weekly_and_never_auto_merges() -> None:
    """The scheduled workflow pins actions, labels PRs, and does not merge."""
    workflow = (_REPO_ROOT / ".github" / "workflows" / "vendor-repin.yml").read_text(
        encoding="utf-8",
    )
    script = (_REPO_ROOT / "scripts" / "ci" / "open_vendor_repin_pr.sh").read_text(
        encoding="utf-8",
    )
    parsed = yaml.safe_load(workflow)

    assert_that(workflow).contains('cron: "0 7 * * 1"')
    assert_that(_TAG_USES.search(workflow)).is_none()
    pins = _SHA_USES.findall(workflow)
    assert_that(pins).is_not_empty()
    assert_that(all(len(pin) == 40 for pin in pins)).is_true()
    assert_that("auto-merge:" in workflow.lower()).is_false()
    assert_that("enable-auto-merge" in workflow.lower()).is_false()
    assert_that(parsed["jobs"]["repin"]["permissions"]["contents"]).is_equal_to(
        "write",
    )
    assert_that(script).contains("new-vendor")
    assert_that(script).contains("automation")
    assert_that(script).contains(
        'git ls-remote --exit-code origin "refs/heads/${branch}"',
    )
    assert_that(script).contains('[[ "$ls_status" -eq 2 ]]')
    assert_that(script).contains(
        'git fetch origin "refs/heads/${branch}:refs/remotes/origin/${branch}"',
    )
    assert_that(script).contains('git checkout -B "$branch" "origin/$branch"')
    assert_that(script).contains('git merge --no-edit "$base_sha"')
    assert_that(script).contains("--force-with-lease")
    assert_that(script).does_not_contain("git push --force ")
    assert_that(workflow).contains("fetch-depth: 0")
    assert_that(workflow).contains("VENDOR_INPUT:")
    assert_that(workflow).contains("VENDOR_ID:")
    assert_that(workflow).contains('"$VENDOR_INPUT"')
    assert_that(workflow).contains('"$VENDOR_ID"')
    assert_that(script).does_not_contain("pr merge")
    assert_that(script).does_not_contain("--auto")
