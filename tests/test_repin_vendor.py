"""Re-pin v2 on the lock/artifact model with local fake upstream revisions."""

import json
import subprocess  # nosec B404 - local git fixture with fixed argv
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from assertpy import assert_that
from repin_helpers import (
    AFTER,
    BEFORE,
    NEW_SHA,
    NEWER_SHA,
    NUMERIC_SHA,
    OLD_SHA,
    consumer_document,
    load_case,
    skill,
)

from ai_skills_engine import cli
from ai_skills_engine.bake import vendor_indexes
from ai_skills_engine.lockfile import read_lock
from ai_skills_engine.manifest.load import read_document
from ai_skills_engine.repin import declined as declined_module
from ai_skills_engine.repin.change import Change
from ai_skills_engine.repin.compare import compare
from ai_skills_engine.repin.declined import declined_pr, marker, markers
from ai_skills_engine.repin.render import FILE_CAP, render_json, render_markdown
from ai_skills_engine.repin.report import RepinReport
from ai_skills_engine.repin.run import repin_vendor
from ai_skills_engine.repin.vendor_pin import VendorPin
from ai_skills_engine.vendors import repin as repin_cli

pytest_plugins = ["repin_helpers"]
GOLDEN = Path(__file__).parent / "fixtures/repin"
type Offline = Callable[..., Path]


def _files(root: Path) -> dict[str, bytes]:
    """Read every committed-style output of the fixture repository.

    Args:
        root: Repository root.

    Returns:
        Relative path to bytes, excluding nothing but directories.
    """
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _component_ids(root: Path) -> set[str]:
    """List capability IDs recorded in the committed lock.

    Args:
        root: Repository root.

    Returns:
        Locked capability IDs.
    """
    return {
        capability.id
        for package in read_lock(root / "ai-skills.lock").packages
        for capability in package.capabilities
    }


def _vendor(root: Path) -> dict[str, Any]:
    """Read the fixture vendor declaration.

    Args:
        root: Repository root.

    Returns:
        Vendor mapping.
    """
    return dict(read_document(root / "ai-skills.yaml")["vendors"][0])


@pytest.mark.parametrize("name", ["updated", "failed"])
def test_golden_bodies_are_byte_identical(name: str) -> None:
    """Rendering the same indexes twice matches the pinned golden bodies."""
    first = compare(**load_case(GOLDEN / f"{name}.input.json"))
    second = compare(**load_case(GOLDEN / f"{name}.input.json"))
    assert_that(render_markdown(first)).is_equal_to(render_markdown(second))
    assert_that(render_json(first)).is_equal_to(render_json(second))
    assert_that(render_markdown(first)).is_equal_to(
        (GOLDEN / f"{name}.body.md.txt").read_text(encoding="utf-8")
    )
    assert_that(render_json(first)).is_equal_to(
        (GOLDEN / f"{name}.body.json.txt").read_text(encoding="utf-8")
    )


def test_body_sections_are_in_fixed_order_without_timestamps() -> None:
    """The body uses the documented section order and ends with the marker."""
    body = (GOLDEN / "updated.body.md.txt").read_text(encoding="utf-8")
    headings = [line for line in body.splitlines() if line.startswith("#")]
    assert_that(headings).is_equal_to(
        [
            "## Vendor re-pin: `example`",
            "### Pin",
            "### SemVer advice (advisory)",
            "### Capabilities",
            "#### Unapplied: identical content at a new ID",
            "### Files",
            "### Resources",
            "### Lineage",
            "### License and notice",
            "### Coverage",
            "### Collisions",
            "### Selectors",
            "### Path drift",
            "### Digests",
        ]
    )
    assert_that(body.rstrip("\n").splitlines()[-1]).is_equal_to(
        marker(vendor="example", revision=NEW_SHA)
    )
    assert_that(body).does_not_match(r"20\d\d-\d\d-\d\d")


def test_body_includes_semver_level_and_every_reason() -> None:
    """Every advisory reason from recommend_semver is rendered in both forms."""
    report = compare(**load_case(GOLDEN / "updated.input.json"))
    advice = report.semver
    assert_that(advice).is_not_none()
    level, reasons = getattr(advice, "level", None), getattr(advice, "reasons", ())
    assert_that(level).is_equal_to("major")
    assert_that(reasons).is_not_empty()
    markdown = render_markdown(report)
    payload = json.loads(render_json(report))
    assert_that(markdown).contains("Level: **major**")
    for reason in reasons:
        assert_that(markdown).contains(f"- {reason}")
    assert_that(payload["semver"]).is_equal_to(
        {"level": "major", "reasons": list(reasons)}
    )


def test_files_are_capped_in_markdown_and_json() -> None:
    """At most FILE_CAP file lines are listed; the remainder is counted."""
    files = tuple(
        Change(subject="pub/pkg:skill/big", kind="+", detail=f"file-{index:03}.md")
        for index in range(FILE_CAP + 7)
    )
    report = RepinReport(
        pin=VendorPin(
            id="pub",
            repo="owner/pub",
            publisher="pub",
            display_ref="latest",
            old_sha=OLD_SHA,
            new_sha=NEW_SHA,
        ),
        status="updated",
        files=files,
    )
    markdown = render_markdown(report)
    payload = json.loads(render_json(report))
    assert_that(markdown.count("  - `+` ")).is_equal_to(FILE_CAP)
    assert_that(markdown).contains("7 more file change(s) omitted")
    assert_that(payload["files"]).is_length(FILE_CAP)
    assert_that(payload["filesOmitted"]).is_equal_to(7)


def test_marker_round_trips() -> None:
    """The rendered marker identifies vendor and revision exactly."""
    body = (GOLDEN / "updated.body.md.txt").read_text(encoding="utf-8")
    assert_that(markers(body)).is_equal_to({("example", NEW_SHA)})


def _gh(pulls: list[dict[str, Any]], calls: list[list[str]]) -> Callable[..., str]:
    """Build a fake ``gh`` runner.

    Args:
        pulls: Closed PR records to return.
        calls: Receives each argv.

    Returns:
        Runner.
    """

    def run(argv: list[str]) -> str:
        """Return the closed PR listing.

        Args:
            argv: ``gh`` arguments.

        Returns:
            JSON listing.
        """
        calls.append(argv)
        return json.dumps(pulls)

    return run


def test_declined_lookup_matches_only_the_same_unmerged_revision() -> None:
    """A closed unmerged PR declines R; merged PRs and newer revisions do not."""
    calls: list[list[str]] = []
    runner = _gh(
        [
            {"number": 9, "mergedAt": None, "body": "x", "comments": []},
            {
                "number": 12,
                "mergedAt": None,
                "body": "",
                "comments": [{"body": marker(vendor="example", revision=NEW_SHA)}],
            },
            {
                "number": 11,
                "mergedAt": "2026-10-01T00:00:00Z",
                "body": marker(vendor="example", revision=NEWER_SHA),
                "comments": [],
            },
            {
                "number": 10,
                "mergedAt": None,
                "body": marker(vendor="example", revision=NEW_SHA),
                "comments": [],
            },
        ],
        calls,
    )
    assert_that(
        declined_pr(vendor="example", revision=NEW_SHA, runner=runner)
    ).is_equal_to(10)
    assert_that(
        declined_pr(vendor="example", revision=NEWER_SHA, runner=runner)
    ).is_none()
    assert_that(declined_pr(vendor="other", revision=NEW_SHA, runner=runner)).is_none()
    assert_that(calls[0][:4]).is_equal_to(["pr", "list", "--state", "closed"])


def test_declined_revision_is_skipped_but_a_newer_one_proceeds(
    offline: Offline,
) -> None:
    """A declined revision never reopens; a newer revision re-pins normally."""
    root = offline(
        {OLD_SHA: BEFORE, NEW_SHA: AFTER, NEWER_SHA: AFTER}, consumer_document()
    )
    before = _files(root)
    lookups: list[tuple[str, str]] = []

    def declined(vendor: str, revision: str) -> int | None:
        lookups.append((vendor, revision))
        return 41 if revision == NEW_SHA else None

    skipped = repin_vendor(
        root=root, vendor_id="example", revision=NEW_SHA, declined=declined
    )
    assert_that(skipped.status).is_equal_to("declined")
    assert_that(_files(root)).is_equal_to(before)
    assert_that(render_markdown(skipped)).contains("declined").does_not_contain(
        "ai-skills-repin"
    )
    updated = repin_vendor(
        root=root, vendor_id="example", revision=NEWER_SHA, declined=declined
    )
    assert_that(updated.status).is_equal_to("updated")
    assert_that(_vendor(root)["sha"]).is_equal_to(NEWER_SHA)
    assert_that(lookups).is_equal_to([("example", NEW_SHA), ("example", NEWER_SHA)])


def test_cli_skip_declined_queries_gh(
    offline: Offline,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The public CLI consults closed PRs and logs the skipped revision."""
    root = offline({OLD_SHA: BEFORE, NEW_SHA: AFTER}, consumer_document())
    calls: list[list[str]] = []
    monkeypatch.setattr(
        declined_module,
        "run_gh",
        _gh(
            [
                {
                    "number": 7,
                    "mergedAt": None,
                    "body": marker(vendor="example", revision=NEW_SHA),
                }
            ],
            calls,
        ),
    )
    before = _files(root)
    status = cli.main(
        [
            "--repo-root",
            str(root),
            "repin",
            "--vendor",
            "example",
            "--revision",
            NEW_SHA,
            "--skip-declined",
        ]
    )
    assert_that(status).is_zero()
    assert_that(calls).is_length(1)
    assert_that(capsys.readouterr().err).contains("declined in closed PR #7")
    assert_that(_files(root)).is_equal_to(before)


def test_repin_updates_pin_lock_and_reports_delta(offline: Offline) -> None:
    """A clean re-pin moves the pin, rewrites the lock and diffs the indexes."""
    root = offline({OLD_SHA: BEFORE, NEW_SHA: AFTER}, consumer_document())
    report = repin_vendor(root=root, vendor_id="example", revision=NEW_SHA)
    assert_that(report.status).is_equal_to("updated")
    assert_that(_vendor(root)["sha"]).is_equal_to(NEW_SHA)
    assert_that(
        [item.sha for item in read_lock(root / "ai-skills.lock").vendors]
    ).is_equal_to([NEW_SHA])
    assert_that(_component_ids(root)).contains(
        "example/tools:skill/delta", "example/tools:skill/gamma"
    ).does_not_contain("example/tools:skill/beta")
    assert_that((root / "vendors.yaml").read_text(encoding="utf-8")).contains(NEW_SHA)
    assert_that(report.unapplied_moves).is_equal_to(
        (
            Change(
                subject="example/tools:skill/beta",
                kind="identical-content",
                detail="example/tools:skill/gamma",
            ),
        )
    )
    assert_that([item.kind for item in report.capabilities]).does_not_contain("renamed")
    assert_that(cli.main(["--repo-root", str(root), "lock", "--check"])).is_zero()

    def engine_independent(body: str) -> list[str]:
        """Drop tar digests, which embed the installed engine version."""
        return [line for line in body.splitlines() if "artifactDigest" not in line]

    assert_that(engine_independent(render_markdown(report))).is_equal_to(
        engine_independent((GOLDEN / "updated.body.md.txt").read_text(encoding="utf-8"))
    )


def test_unchanged_pin_writes_nothing(offline: Offline) -> None:
    """Re-pinning to the current revision reports no delta and writes nothing."""
    root = offline({OLD_SHA: BEFORE}, consumer_document())
    before = _files(root)
    report = repin_vendor(root=root, vendor_id="example", revision=OLD_SHA)
    assert_that(report.status).is_equal_to("unchanged")
    assert_that(render_markdown(report)).contains("Pin already current")
    assert_that(_files(root)).is_equal_to(before)


@pytest.mark.parametrize(
    ("tree", "skills", "expected"),
    [
        (
            {**BEFORE, "skills/beta/SKILL.md": None, "moved/beta/SKILL.md": "beta"},
            ["alpha", "beta"],
            {"skills": ["alpha"], "extraSkills": ["moved/beta"]},
        ),
        (
            {
                "pkg/skills/alpha/SKILL.md": skill("alpha", "alpha body"),
                "pkg/skills/beta/SKILL.md": skill("beta", "beta body"),
                "LICENSE": "MIT\n",
            },
            ["alpha", "beta"],
            {"skillsRoot": "pkg/skills", "skills": ["alpha", "beta"]},
        ),
    ],
    ids=["skill-move", "root-move"],
)
def test_unique_move_is_reconciled_without_changing_ids(
    offline: Offline,
    tree: dict[str, str | None],
    skills: list[str],
    expected: dict[str, Any],
) -> None:
    """Exactly one identical same-name candidate rewrites the mapping path."""
    moved = {
        key: (skill("beta", "beta body") if value == "beta" else value)
        for key, value in tree.items()
        if value is not None
    }
    root = offline({OLD_SHA: BEFORE, NEW_SHA: moved}, consumer_document(skills=skills))
    ids = _component_ids(root)
    report = repin_vendor(root=root, vendor_id="example", revision=NEW_SHA)
    assert_that(report.action_required).is_empty()
    package = _vendor(root)["mapping"]["packages"][0]
    for key, value in expected.items():
        assert_that(package[key]).is_equal_to(value)
    assert_that(_component_ids(root)).is_equal_to(ids)
    assert_that([item.status for item in report.drift]).contains("reconciled")
    assert_that(render_markdown(report)).contains("reconciled `mapping.")


@pytest.mark.parametrize(
    ("extra", "status", "candidates"),
    [
        (
            {"x/beta/SKILL.md": "beta", "y/beta/SKILL.md": "beta"},
            "ambiguous",
            ("x/beta", "y/beta"),
        ),
        ({}, "missing", ()),
    ],
    ids=["ambiguous", "missing"],
)
def test_ambiguous_or_missing_move_fails_and_lists_candidates(
    offline: Offline,
    extra: dict[str, str],
    status: str,
    candidates: tuple[str, ...],
) -> None:
    """Zero or several candidates fail closed, list them and write nothing."""
    tree = {key: value for key, value in BEFORE.items() if "beta" not in key}
    tree.update({key: skill("beta", "beta body") for key in extra})
    root = offline(
        {OLD_SHA: BEFORE, NEW_SHA: tree}, consumer_document(skills=["alpha", "beta"])
    )
    before = _files(root)
    report = repin_vendor(root=root, vendor_id="example", revision=NEW_SHA)
    assert_that(report.status).is_equal_to("failed")
    assert_that([(item.status, item.candidates) for item in report.drift]).contains(
        (status, candidates)
    )
    body = render_markdown(report)
    assert_that(body).contains("### Action required", "'beta'")
    for candidate in candidates:
        assert_that(body).contains(candidate)
    assert_that(_files(root)).is_equal_to(before)


def test_dead_selector_fails_and_names_the_selector(offline: Offline) -> None:
    """An include selector matching nothing at the new revision fails the re-pin."""
    selector = "example/tools:skill/beta"
    tree = {key: value for key, value in BEFORE.items() if "beta" not in key}
    root = offline(
        {OLD_SHA: BEFORE, NEW_SHA: tree},
        consumer_document(include=["example/tools:skill/alpha", selector]),
        legacy=False,
    )
    before = _files(root)
    report = repin_vendor(root=root, vendor_id="example", revision=NEW_SHA)
    assert_that(report.status).is_equal_to("failed")
    assert_that("\n".join(report.action_required)).contains(
        f"Dead selector include: {selector!r}"
    )
    assert_that([(item.selector, item.status) for item in report.selectors]).contains(
        (selector, "dead")
    )
    assert_that(_files(root)).is_equal_to(before)


def test_declared_rename_rewrites_selectors(offline: Offline) -> None:
    """A consumer migration renames the mapped selector and include selector."""
    migration = {"from": "example/tools:skill/beta", "to": "example/tools:skill/gamma"}
    root = offline(
        {OLD_SHA: BEFORE, NEW_SHA: AFTER},
        consumer_document(
            skills=["alpha", "beta"],
            include=["example/tools:skill/alpha", "example/tools:skill/beta"],
            overrides={"migrations": [migration]},
        ),
        legacy=False,
    )
    report = repin_vendor(root=root, vendor_id="example", revision=NEW_SHA)
    assert_that(report.action_required).is_empty()
    vendor = _vendor(root)
    assert_that(vendor["mapping"]["packages"][0]["skills"]).is_equal_to(
        ["alpha", "gamma"]
    )
    assert_that(vendor["include"]).is_equal_to(
        ["example/tools:skill/alpha", "example/tools:skill/gamma"]
    )
    assert_that(report.capabilities).contains(
        Change(
            subject="example/tools:skill/beta",
            kind="renamed",
            detail="example/tools:skill/gamma (consumer)",
        )
    )
    assert_that(report.unapplied_moves).is_empty()
    assert_that({item.status for item in report.selectors}).contains("renamed")


def test_undeclared_identical_move_is_reported_never_applied(offline: Offline) -> None:
    """Identical content under a new name is listed, and its selector fails."""
    root = offline(
        {OLD_SHA: BEFORE, NEW_SHA: AFTER}, consumer_document(skills=["alpha", "beta"])
    )
    before = _files(root)
    report = repin_vendor(root=root, vendor_id="example", revision=NEW_SHA)
    assert_that(report.status).is_equal_to("failed")
    assert_that(report.unapplied_moves).contains(
        Change(subject="skills/beta", kind="identical-content", detail="skills/gamma")
    )
    assert_that("\n".join(report.action_required)).contains("'beta'")
    assert_that(render_markdown(report)).contains(
        "#### Unapplied: identical content at a new ID", "`skills/gamma`"
    )
    assert_that(_files(root)).is_equal_to(before)


def test_no_manifest_rewrite_turns_reconcile_into_action(offline: Offline) -> None:
    """Automation that cannot publish the manifest reports the needed edit."""
    tree = {key: value for key, value in BEFORE.items() if "beta" not in key}
    tree["moved/beta/SKILL.md"] = skill("beta", "beta body")
    root = offline(
        {OLD_SHA: BEFORE, NEW_SHA: tree}, consumer_document(skills=["alpha", "beta"])
    )
    before = _files(root)
    report = repin_vendor(
        root=root, vendor_id="example", revision=NEW_SHA, rewrite_manifest=False
    )
    assert_that(report.status).is_equal_to("failed")
    assert_that("\n".join(report.action_required)).contains(
        "Manifest edit required", "moved/beta", "--baseline-ref"
    )
    assert_that(_files(root)).is_equal_to(before)


def test_pin_write_quotes_parser_divergent_sha(offline: Offline) -> None:
    """The writer quotes a SHA read differently by YAML 1.1 and YAML 1.2."""
    root = offline({OLD_SHA: BEFORE, NUMERIC_SHA: BEFORE}, consumer_document())
    report = repin_vendor(root=root, vendor_id="example", revision=NUMERIC_SHA)
    assert_that(report.status).is_equal_to("updated")
    text = (root / "ai-skills.yaml").read_text(encoding="utf-8")
    assert_that(text).contains(f'sha: "{NUMERIC_SHA}"')
    assert_that(yaml.safe_load(text)["vendors"][0]["sha"]).is_equal_to(NUMERIC_SHA)
    assert_that(_vendor(root)["sha"]).is_equal_to(NUMERIC_SHA)


@pytest.mark.parametrize("quoted", [False, True], ids=["plain", "quoted"])
def test_divergent_sha_controls_plain_rejected_quoted_valid(
    offline: Offline, quoted: bool
) -> None:
    """A plain divergent SHA fails before any write; the quoted spelling works."""
    root = offline({OLD_SHA: BEFORE, NUMERIC_SHA: BEFORE}, consumer_document())
    manifest = root / "ai-skills.yaml"
    spelling = f'"{NUMERIC_SHA}"' if quoted else NUMERIC_SHA
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            f"sha: {OLD_SHA}", f"sha: {spelling}"
        ),
        encoding="utf-8",
    )
    before = _files(root)
    if quoted:
        report = repin_vendor(root=root, vendor_id="example", keep_sha=True)
        assert_that(report.status).is_equal_to("unchanged")
        assert_that(_files(root)).is_equal_to(before)
        return
    with pytest.raises(ValueError, match="unquoted sha") as error:
        repin_vendor(root=root, vendor_id="example", keep_sha=True)
    assert_that(str(error.value)).contains(f'sha: "{NUMERIC_SHA}"')
    assert_that(_files(root)).is_equal_to(before)


def test_failure_after_publication_restores_every_file(
    offline: Offline, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A late compatibility failure restores manifest, lock and generated data."""
    root = offline({OLD_SHA: BEFORE, NEW_SHA: AFTER}, consumer_document())
    before = _files(root)
    real = vendor_indexes.bake

    def failing_bake(*, repo_root: Path) -> None:
        real(repo_root=repo_root)
        raise RuntimeError("injected compatibility failure")

    monkeypatch.setattr(vendor_indexes, "bake", failing_bake)
    with pytest.raises(RuntimeError, match="injected"):
        repin_vendor(root=root, vendor_id="example", revision=NEW_SHA)
    assert_that(_files(root)).is_equal_to(before)


def _git(root: Path, *args: str) -> str:
    """Run git with an isolated configuration.

    Args:
        root: Repository.
        *args: Git arguments.

    Returns:
        Standard output.
    """
    return subprocess.run(  # nosec B603 B607 - fixed local git argv
        [
            "git",
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null"},
    ).stdout


def test_cli_keep_sha_baseline_ref_summarizes_base_branch(
    offline: Offline, capsys: pytest.CaptureFixture[str]
) -> None:
    """Renovate-style runs diff against the base branch's manifest and lock."""
    root = offline({OLD_SHA: BEFORE, NEW_SHA: AFTER}, consumer_document())
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    manifest = root / "ai-skills.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(OLD_SHA, NEW_SHA),
        encoding="utf-8",
    )
    summary = root.parent / "summary.md"
    status = cli.main(
        [
            "--repo-root",
            str(root),
            "repin",
            "--all",
            "--keep-sha",
            "--no-manifest-rewrite",
            "--baseline-ref",
            "HEAD",
            "--summary-path",
            str(summary),
        ]
    )
    assert_that(status).described_as(capsys.readouterr().err).is_zero()
    body = summary.read_text(encoding="utf-8")
    assert_that(body).contains(
        f"`{OLD_SHA}` → `{NEW_SHA}`",
        f"compare/{OLD_SHA}...{NEW_SHA}",
        marker(vendor="example", revision=NEW_SHA),
    )
    assert_that(
        [item.sha for item in read_lock(root / "ai-skills.lock").vendors]
    ).is_equal_to([NEW_SHA])
    changed = _git(root, "status", "--porcelain").split()
    assert_that(changed).contains("ai-skills.lock", "ai-skills.yaml")


def test_cli_json_failure_exits_one_with_action_required(
    offline: Offline, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--json`` stays parseable and a failed re-pin exits 1 with a body."""
    root = offline(
        {OLD_SHA: BEFORE, NEW_SHA: AFTER}, consumer_document(skills=["alpha", "beta"])
    )
    summary = root.parent / "body.md"
    capsys.readouterr()
    status = cli.main(
        [
            "--repo-root",
            str(root),
            "repin",
            "--vendor",
            "example",
            "--revision",
            NEW_SHA,
            "--json",
            "--summary-path",
            str(summary),
        ]
    )
    captured = capsys.readouterr()
    assert_that(status).is_equal_to(1)
    payload = json.loads(captured.out)
    assert_that(payload["status"]).is_equal_to("failed")
    assert_that(payload["actionRequired"]).is_not_empty()
    assert_that(summary.read_text(encoding="utf-8")).contains("### Action required")
    assert_that(captured.err).contains("repin: example: Dead selector")


def test_cli_rejects_unknown_vendor_and_bad_revision(
    offline: Offline, capsys: pytest.CaptureFixture[str]
) -> None:
    """Selection errors fail before any write with a clear message."""
    root = offline({OLD_SHA: BEFORE}, consumer_document())
    args = ["--repo-root", str(root), "repin"]
    assert_that(
        cli.main([*args, "--vendor", "missing", "--revision", NEW_SHA])
    ).is_equal_to(1)
    assert_that(capsys.readouterr().err).contains("Unknown vendor id: missing")
    assert_that(
        cli.main([*args, "--vendor", "example", "--revision", "HEAD"])
    ).is_equal_to(1)
    assert_that(capsys.readouterr().out).contains("Revision must be a lowercase")
    assert_that(repin_cli.list_vendor_ids(repo_root=root)).is_equal_to(("example",))


def _upstream_manifest(*, name: str, migrations: list[dict[str, str]]) -> str:
    """Render a vendor's own manifest publishing one skill.

    Args:
        name: Capability ID and directory name.
        migrations: Publisher-local identity migrations.

    Returns:
        Manifest YAML.
    """
    document: dict[str, Any] = {
        "apiVersion": "ai-skills.dev/v1",
        "publisher": {"id": "upstream", "repo": "owner/example"},
        "packages": [
            {
                "id": "kit",
                "capabilities": [{"id": name, "path": f"skills/{name}"}],
            }
        ],
        "exports": ["kit"],
    }
    if migrations:
        document["overrides"] = {"migrations": migrations}
    return yaml.safe_dump(document, sort_keys=False)


def test_upstream_declared_rename_rewrites_consumer_selectors(offline: Offline) -> None:
    """A publisher-local migration in the upstream manifest renames selectors."""
    migration = {"from": "upstream/kit:skill/old", "to": "upstream/kit:skill/new"}
    trees = {
        OLD_SHA: {
            "ai-skills.yaml": _upstream_manifest(name="old", migrations=[]),
            "skills/old/SKILL.md": skill("old", "kit body"),
            "LICENSE": "MIT\n",
        },
        NEW_SHA: {
            "ai-skills.yaml": _upstream_manifest(name="new", migrations=[migration]),
            "skills/new/SKILL.md": skill("new", "kit body"),
            "LICENSE": "MIT\n",
        },
    }
    document = consumer_document(include=["upstream/kit:skill/old"])
    document["vendors"][0].pop("mapping")
    document["exports"] = ["git-pr"]
    root = offline(trees, document, legacy=False)
    report = repin_vendor(root=root, vendor_id="example", revision=NEW_SHA)
    assert_that(report.action_required).is_empty()
    assert_that(_vendor(root)["include"]).is_equal_to(["upstream/kit:skill/new"])
    assert_that(report.capabilities).contains(
        Change(
            subject="upstream/kit:skill/old",
            kind="renamed",
            detail="upstream/kit:skill/new (upstream)",
        )
    )
    assert_that(report.unapplied_moves).is_empty()
