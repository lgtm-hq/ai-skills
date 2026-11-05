"""Local fake upstream revisions and consumer repositories for re-pin tests.

Nothing here touches the network: sources come from in-memory trees keyed by
revision, and the vendor-index listing is served from the same trees.
"""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from ai_skills_engine.bake import vendor_indexes, vendor_plugins
from ai_skills_engine.manifest.edit import dump_document
from ai_skills_engine.registry.vendor import Vendor

OLD_SHA = "0123456789abcdef0123456789abcdef01234567"
NEW_SHA = "89abcdef0123456789abcdef0123456789abcdef"
NEWER_SHA = "fedcba9876543210fedcba9876543210fedcba98"
# Plain 1e111... is a YAML 1.2 float but a YAML 1.1 string: writers must quote.
NUMERIC_SHA = "1e" + "1" * 38
PACKAGE_JSON = '{\n  "name": "@lgtm-hq/ai-skills",\n  "version": "0.0.0-dev"\n}\n'
type Tree = dict[str, str]


def skill(name: str, body: str) -> str:
    """Render a minimal SKILL.md.

    Args:
        name: Frontmatter name.
        body: Markdown body.

    Returns:
        File text.
    """
    return f"---\nname: {name}\ndescription: {name} skill.\n---\n{body}\n"


BEFORE: Tree = {
    "skills/alpha/SKILL.md": skill("alpha", "alpha body"),
    "skills/beta/SKILL.md": skill("beta", "beta body"),
    "template/placeholder/SKILL.md": skill("placeholder", "not ingested"),
    "LICENSE": "MIT\n",
}
AFTER: Tree = {
    "skills/alpha/SKILL.md": skill("alpha", "alpha body, revised"),
    "skills/alpha/reference.md": "Reference.\n",
    "skills/delta/SKILL.md": skill("delta", "delta body"),
    "skills/gamma/SKILL.md": skill("beta", "beta body"),
    "LICENSE": "MIT\n",
}


class FakeUpstream:
    """Serve fixed trees per revision instead of downloading archives.

    Args:
        trees: Revision to tree.

    Attributes:
        trees: Revision to relative path to text.
        calls: ``repo@sha`` of every acquisition.
    """

    def __init__(self, trees: Mapping[str, Tree]) -> None:
        self.trees = dict(trees)
        self.calls: list[str] = []

    def fetch(self, *, vendor: Vendor, dest: Path) -> None:
        """Write the pinned tree.

        Args:
            vendor: Requested pin.
            dest: New directory.
        """
        self.calls.append(f"{vendor.repo}@{vendor.sha}")
        write_tree(dest=dest, tree=self.trees[vendor.sha])

    def paths(self, *, vendor: Vendor) -> list[str]:
        """List the pinned tree for the vendor-index baker.

        Args:
            vendor: Requested pin.

        Returns:
            Sorted relative paths.
        """
        return sorted(self.trees[vendor.sha])


def write_tree(*, dest: Path, tree: Tree) -> None:
    """Materialize a tree.

    Args:
        dest: Destination directory.
        tree: Relative path to text.
    """
    for relative, text in tree.items():
        path = dest / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def consumer_document(
    *,
    sha: str = OLD_SHA,
    skills: object = "*",
    overrides: dict[str, Any] | None = None,
    include: list[str] | None = None,
) -> dict[str, Any]:
    """Build a consumer manifest mapping one manifestless vendor.

    Args:
        sha: Vendor pin.
        skills: Mapped ``skills`` selector.
        overrides: Consumer overrides.
        include: Vendor include selectors.

    Returns:
        Manifest mapping.
    """
    vendor: dict[str, Any] = {
        "id": "example",
        "repo": "owner/example",
        "sha": sha,
        "branch": "main",
        "displayRef": "latest",
        "license": "MIT",
        "homepage": "https://github.com/owner/example",
        "mapping": {
            "skillRoots": ["skills"],
            "packages": [
                {
                    "id": "tools",
                    "description": "Example tools.",
                    "skillsRoot": "skills",
                    "skills": skills,
                }
            ],
        },
    }
    if include is not None:
        vendor["include"] = include
    document: dict[str, Any] = {
        "apiVersion": "ai-skills.dev/v1",
        "publisher": {"id": "consumer", "repo": "fixture/consumer"},
        "packages": [
            {
                "id": "git-pr",
                "name": "Git",
                "description": "First-party fixture package.",
                "capabilities": [{"id": "branch", "path": "skills/branch"}],
                "x-legacy-group": "git-pr",
            }
        ],
        "exports": ["git-pr", "example/tools"],
        "policy": {"provenance": {"mode": "strict"}},
        "vendors": [vendor],
    }
    if overrides:
        document["overrides"] = overrides
    return document


def write_consumer(*, root: Path, document: dict[str, Any]) -> None:
    """Write a consumer repository (manifest, first-party skill, npm stub).

    Args:
        root: Repository root.
        document: Manifest mapping.
    """
    write_tree(
        dest=root,
        tree={
            "skills/branch/SKILL.md": skill("branch", "first-party"),
            "npm/ai-skills/package.json": PACKAGE_JSON,
            "ai-skills.yaml": dump_document(document),
        },
    )


@pytest.fixture
def offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    """Prepare an isolated cache and patch acquisition to a fake upstream.

    Args:
        tmp_path: Test directory.
        monkeypatch: Patches acquisition and forbids HTTP.

    Returns:
        Factory ``(trees, document) -> repository root``.
    """

    def no_network(**kwargs: object) -> bytes:
        """Fail on any HTTP request.

        Args:
            **kwargs: Request description.

        Raises:
            AssertionError: Always.
        """
        raise AssertionError(f"unexpected network request: {kwargs.get('host')}")

    monkeypatch.setenv("AI_SKILLS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(vendor_plugins, "_http_get_bytes", no_network)

    def create(
        trees: Mapping[str, Tree], document: dict[str, Any], *, legacy: bool = True
    ) -> Path:
        """Write a consumer locked at its current pin.

        Args:
            trees: Revision to upstream tree.
            document: Manifest mapping.
            legacy: Also publish compatibility outputs (``vendors.yaml`` etc.).

        Returns:
            Repository root with ai-skills.lock and optional compatibility outputs.
        """
        upstream = FakeUpstream(trees)
        monkeypatch.setattr(vendor_plugins, "_fetch_vendor_tree", upstream.fetch)
        monkeypatch.setattr(vendor_indexes, "_fetch_tree_paths", upstream.paths)
        root = tmp_path / "repository"
        write_consumer(root=root, document=document)
        from ai_skills_engine import cli
        from ai_skills_engine.vendors import manage

        if legacy:
            manage.refresh(repo_root=root)
        if cli.main(["--repo-root", str(root), "lock"]) != 0:
            raise AssertionError("fixture lock failed")
        return root

    return create


def load_case(path: Path) -> dict[str, Any]:
    """Load a captured ``compare`` input as keyword arguments.

    Args:
        path: ``*.input.json`` golden input.

    Returns:
        Keyword arguments for :func:`ai_skills_engine.repin.compare.compare`.
    """
    import json

    from ai_skills_engine.repin.catalog_side import CatalogSide
    from ai_skills_engine.repin.change import Change
    from ai_skills_engine.repin.drift import Drift
    from ai_skills_engine.repin.selector_status import SelectorStatus
    from ai_skills_engine.repin.vendor_pin import VendorPin

    case = json.loads(path.read_text(encoding="utf-8"))

    def side(value: dict[str, Any]) -> CatalogSide:
        return CatalogSide(
            index=value["index"],
            files=value["files"],
            artifact_digests=value["artifactDigests"],
            diagnostics=tuple(value["diagnostics"]),
        )

    return {
        "pin": VendorPin(**case["pin"]),
        "before": side(case["before"]),
        "after": side(case["after"]),
        "migrations": {key: tuple(value) for key, value in case["migrations"].items()},
        "selectors": [SelectorStatus(**item) for item in case["selectors"]],
        "drift": [
            Drift(
                location=item["location"],
                selector=item["selector"],
                old_path=item["oldPath"],
                status=item["status"],
                candidates=tuple(item["candidates"]),
            )
            for item in case["drift"]
        ],
        "moves": [Change(**item) for item in case["moves"]],
        "skill_dirs": (tuple(case["skillDirs"][0]), tuple(case["skillDirs"][1])),
        "action_required": case["actionRequired"],
        "upstream_moves": case["upstreamMoves"],
    }
