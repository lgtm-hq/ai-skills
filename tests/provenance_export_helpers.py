"""Offline publication inputs for repeated identity and materialization evidence."""

import json
import shutil
from pathlib import Path

from ai_skills_engine.inventory.load import load_inventory
from ai_skills_engine.inventory.payload import payload_files, tree_digest
from ai_skills_engine.manifest.edit import dump_document


def materialized_exports(*, root: Path, kind: str, changed: bool, reverse: bool) -> str:
    """Declare two independently checked copies of one imported identity.

    Args:
        root: Existing two-hop snapshot fixture.
        kind: Capability or resource copy.
        changed: Whether the second copy has incompatible bytes.
        reverse: Whether to reverse index declaration order.

    Returns:
        The stable imported identity under test.
    """
    inventory = load_inventory(root / "x")
    record = (
        inventory.capabilities[0] if kind == "capability" else inventory.resources[0]
    )
    source = root / "x" / record.source_path
    claims = []
    for name in ("copy-a", "copy-b"):
        target = root / "y" / name
        shutil.copytree(src=source, dst=target)
        if changed and name == "copy-b":
            file = next(path for path in target.rglob("*") if path.is_file())
            file.write_text(file.read_text() + "\nDifferent materialized bytes.\n")
        claim = json.loads(record.lineage[0].to_json())
        claim["lineage"][0]["rev"] = "a" * 40
        hop = dict(claim["lineage"][-1])
        hop.update(
            publisher="y",
            origin="github.com/fixture/y",
            rev="b" * 40,
            path=name,
            treeDigest="sha256:" + tree_digest(payload_files(target)),
        )
        claim["lineage"].append(hop)
        claims.append(claim)
    index = root / "y/ai-skills.lineage.json"
    others = [r for r in json.loads(index.read_text()) if r["id"] != str(record.id)]
    index.write_text(json.dumps([*others, *(reversed(claims) if reverse else claims)]))
    return str(record.id)


def diamond_exports(
    *, root: Path, reverse: bool, missing: bool = False
) -> dict[str, Path]:
    """Build two pins of X exported through distinct publishers with distinct edges.

    Args:
        root: Empty fixture directory.
        reverse: Whether Z imports W before Y.
        missing: Whether both pins also require unavailable targets.

    Returns:
        Explicit offline vendor roots for the final consumer.
    """
    for name in ("a", "b", "xa", "xb", "y", "w", "z"):
        (root / name).mkdir(parents=True)
    for name in ("a", "b"):
        (root / name / "data.txt").write_text(f"Resource from {name}.\n")
        document = {
            "apiVersion": "ai-skills.dev/v1",
            "publisher": {"id": name, "repo": f"fixture/{name}"},
            "packages": [
                {"id": "tools", "resources": [{"id": "data", "path": "data.txt"}]}
            ],
            "exports": ["tools"],
        }
        (root / name / "ai-skills.yaml").write_text(dump_document(document))
        pin = root / ("x" + name)
        for skill in ("plain", "dep-" + name, "related-" + name):
            directory = pin / skill
            directory.mkdir()
            (directory / "SKILL.md").write_text(
                f"---\nname: {skill}\ndescription: Fixture.\n---\n{skill}.\n"
            )
        document = {
            "apiVersion": "ai-skills.dev/v1",
            "publisher": {"id": "x", "repo": "fixture/x"},
            "packages": [
                {
                    "id": "tools",
                    "capabilities": [
                        {
                            "id": "plain",
                            "path": "plain",
                            "requires": [
                                f"x/tools:skill/dep-{name}",
                                *([f"x/tools:skill/missing-{name}"] if missing else []),
                            ],
                            "related": [f"x/tools:skill/related-{name}"],
                            "resources": [f"{name}/tools:resource/data"],
                        },
                        {"id": "dep-" + name, "path": "dep-" + name},
                        {"id": "related-" + name, "path": "related-" + name},
                    ],
                }
            ],
            "vendors": [{"id": name, "repo": f"fixture/{name}", "sha": name * 40}],
            "exports": ["tools", name + "/tools"],
        }
        (pin / "ai-skills.yaml").write_text(dump_document(document))
    for publisher, branch in (("y", "a"), ("w", "b")):
        document = {
            "apiVersion": "ai-skills.dev/v1",
            "publisher": {"id": publisher, "repo": f"fixture/{publisher}"},
            "vendors": [{"id": "x", "repo": "fixture/x", "sha": branch * 40}],
            "exports": ["x/tools", branch + "/tools"],
        }
        (root / publisher / "ai-skills.yaml").write_text(dump_document(document))
    vendors = [
        {"id": "y", "repo": "fixture/y", "sha": "c" * 40},
        {"id": "w", "repo": "fixture/w", "sha": "d" * 40},
    ]
    (root / "z/ai-skills.yaml").write_text(
        dump_document(
            {
                "apiVersion": "ai-skills.dev/v1",
                "publisher": {"id": "z", "repo": "fixture/z"},
                "vendors": list(reversed(vendors)) if reverse else vendors,
                "policy": {"provenance": {"mode": "strict"}},
            }
        )
    )
    return {
        "y": root / "y",
        "y/x": root / "xa",
        "y/x/a": root / "a",
        "w": root / "w",
        "w/x": root / "xb",
        "w/x/b": root / "b",
    }
