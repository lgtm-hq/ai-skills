#!/usr/bin/env python3
"""Regenerate the ## Skills section of AGENTS.md from skills/*/SKILL.md frontmatter.

Output lines match ``scripts/validate.sh`` expectations::

    - `skill-id`: Description text (`skills/skill-id/SKILL.md`)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def _parse_frontmatter_block(body: str) -> tuple[str, str]:
    """Return (name, description) from YAML frontmatter *body* (without delimiters)."""
    name = ""
    description = ""
    lines = body.splitlines()
    i = 0
    root_key_re = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*:\s*")
    while i < len(lines):
        line = lines[i]
        name_eq = re.match(r"^name:\s*(.*)$", line)
        if name_eq:
            name = name_eq.group(1).strip()
            i += 1
            continue
        desc_eq = re.match(r"^description:\s*(.*)$", line)
        if desc_eq:
            first = desc_eq.group(1).strip()
            desc_parts: list[str] = []
            i += 1
            folded_header = bool(
                first in {">-", ">", "|", "|-", "|+"}
                or re.match(r"^>[\-+]?\s*$", first)
                or re.match(r"^\|([\-+]?)\s*$", first),
            )
            if folded_header or first == "":
                while i < len(lines):
                    cont = lines[i]
                    if root_key_re.match(cont):
                        break
                    if re.match(r"^[\t ]+", cont):
                        desc_parts.append(cont.strip())
                        i += 1
                        continue
                    if cont.strip() == "":
                        i += 1
                        continue
                    break
            elif len(first) >= 2 and first[0] == first[-1] and first[0] in "\"'":
                desc_parts.append(first[1:-1])
            else:
                desc_parts.append(first)
            description = " ".join(desc_parts)
            continue
        i += 1
    return name, description


def _read_skill_meta(skill_md: Path) -> tuple[str, str]:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        msg = f"Missing opening --- in {skill_md}"
        raise ValueError(msg)
    end = text.find("\n---\n", 4)
    if end == -1:
        msg = f"Missing closing --- in {skill_md}"
        raise ValueError(msg)
    fm = text[4:end]
    name, description = _parse_frontmatter_block(body=fm)
    if not name or not description:
        msg = f"Missing name or description in {skill_md}"
        raise ValueError(msg)
    return name, description


def _build_skills_section(repo_root: Path) -> tuple[str, int]:
    skills_root = repo_root / "skills"
    bullets: list[str] = []
    for d in sorted(skills_root.iterdir(), key=lambda p: p.name):
        if not d.is_dir():
            continue
        skill_md = d / "SKILL.md"
        if not skill_md.is_file():
            continue
        skill_id, desc = _read_skill_meta(skill_md=skill_md)
        if skill_id != d.name:
            msg = f"name {skill_id!r} != directory {d.name!r} in {skill_md}"
            raise ValueError(msg)
        path_ref = f"`skills/{skill_id}/SKILL.md`"
        line = f"- `{skill_id}`: {desc} ({path_ref})"
        bullets.append(line)
    return "\n".join(bullets), len(bullets)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    agents_path = repo_root / "AGENTS.md"
    text = agents_path.read_text(encoding="utf-8")
    sep = "## Skills\n"
    if sep not in text:
        print("AGENTS.md must contain ## Skills", file=sys.stderr)
        sys.exit(1)
    pre, post = text.split(sep, maxsplit=1)
    match_total = re.search(pattern=r"\nTotal skills:\s*\d+\s*\n", string=post)
    if not match_total:
        print(
            "AGENTS.md must contain a Total skills: line after ## Skills",
            file=sys.stderr,
        )
        sys.exit(1)
    trailer = post[match_total.end() :]
    skill_lines, count = _build_skills_section(repo_root=repo_root)
    new_agents = (
        pre + sep + "\n" + skill_lines + f"\n\nTotal skills: {count}\n\n" + trailer
    )
    agents_path.write_text(new_agents, encoding="utf-8")


if __name__ == "__main__":
    main()
