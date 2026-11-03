"""Shared scalar contract inputs for source, wheel and production native gates."""

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from ai_skills_engine.manifest.edit import dump_document

ROOT = Path(__file__).resolve().parents[3]
CASES: list[dict[str, Any]] = json.loads(
    (ROOT / "tests/fixtures/manifest/scalars.json").read_text()
)


def _base_document() -> dict[str, Any]:
    """Supply a publishable consumer with a digest decoy and two isolated pins."""
    return {
        "apiVersion": "ai-skills.dev/v1",
        "publisher": {"id": "example"},
        "exports": [],
        "x-decoy": "a" * 40,
        "vendors": [
            {
                "id": name,
                "repo": f"{name}/skills",
                "sha": "a" * 40,
                "branch": "main",
                "license": "MIT",
                "homepage": f"https://github.com/{name}/skills",
                "mapping": {"skillRoots": ["skills"]},
            }
            for name in ("mattpocock", "anthropics")
        ],
    }


def scalar_source(
    case: dict[str, Any], quote: str = "", *, indent: int = 2, reverse: bool = False
) -> str:
    """Render a publishable declaration with a chosen target source spelling.

    Args:
        case: External parser contract case.
        quote: Ordinary single/double quote, or plain source.
        indent: Arbitrary valid vendor sequence indentation.
        reverse: Whether to reverse the target record's field order.

    Returns:
        Publishable consumer manifest with two vendors and a digest decoy.
    """
    data = deepcopy(_base_document())
    field, value = case["field"], case["value"]
    data["vendors"][0][field] = value
    if reverse:
        data["vendors"][0] = dict(reversed(data["vendors"][0].items()))
    source = re.sub(
        rf"^    {field}: .*?$",
        lambda _: f"    {field}: {quote}{value}{quote}",
        dump_document(data),
        count=1,
        flags=re.MULTILINE,
    )
    lines = source.splitlines(keepends=True)
    in_vendors = False
    for index, line in enumerate(lines):
        if line.startswith("vendors:"):
            in_vendors = True
        elif in_vendors and line.startswith("  "):
            lines[index] = " " * indent + line[2:]
        elif in_vendors and line.strip():
            in_vendors = False
    return (f"%YAML {case['version']}\n" if case["version"] else "") + "".join(lines)


def line_break_source(*, field: str, separator: str, position: str) -> str:
    """Place a YAML 1.1-only break immediately outside a vendor scalar token.

    Args:
        field: SHA or branch field.
        separator: NEL, LS or PS from external YAML syntax.
        position: Leading or trailing token boundary.

    Returns:
        Publishable consumer whose scalar differs under YAML 1.2.
    """
    value = "a" * 40 if field == "sha" else "main"
    raw = f"{separator}      {value}" if position == "leading" else value + separator
    return re.sub(
        rf"^    {field}: .*?$",
        lambda _: f"    {field}: {raw}",
        dump_document(_base_document()),
        count=1,
        flags=re.MULTILINE,
    )
