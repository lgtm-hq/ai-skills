---
name: coderabbit
description: >-
  Run CodeRabbit CLI for pre-push AI diff review. Use when asked for CodeRabbit,
  cr review, or as part of the default dual pre-push workflow with greptile. Max
  2-3 runs per change set.
---

# CodeRabbit CLI Review

Run **CodeRabbit** (`cr` / `coderabbit`) for automated diff review before push.
Pair with **`greptile`** for the default pre-CI workflow — both tools catch different
issues and mirror CI.

## Relationship to analyze-* skills

The `analyze-code`, `analyze-project`, and `analyze-tests` skills are for
**manual or agent-driven pre-review checks**—they run concrete commands (lintro,
ripgrep, coverage, etc.) and produce structured findings before you open a PR.

This skill uses **CodeRabbit CLI** for external AI diff review. Follow the `lint` and
`test` skills (or the `commit` skill, which includes them) before invoking CodeRabbit.
Do not duplicate full analyze rubrics here.

## Relationship to greptile

Default pre-push flow when CI runs both tools:

```text
commit → [greptile ‖ coderabbit] → pr
```

Each step names the skill to follow.

Run **greptile** and **coderabbit** in parallel when possible. Do not re-run on
unchanged code.

## Commands

- `cr -h` / `coderabbit --help` — Show CodeRabbit help
- `coderabbit review --agent --type committed --base main` — Full branch diff against
  main (default for agents; matches CI intent)
- `coderabbit review --agent --type uncommitted` — Uncommitted (staged + unstaged);
  quick spot check
- `coderabbit doctor` — Verify install, auth, and Git repo readiness
- `coderabbit review findings` — Replay findings from the last local review

`cr` is an alias for `coderabbit`. `--prompt-only` is deprecated; use `--agent`.

## Rules

- Max **2–3** CodeRabbit runs per change set (Pro plan: 5 CLI reviews per developer —
  [rate limits](https://docs.coderabbit.ai/management/plans#rate-limits))
- Always use `--agent` for agent workflows (structured JSON output)
- **Default to `--base main`** unless the repo uses a different default branch
- Reviews can take 7–30+ minutes — run in the background when possible
- Must run from an initialized Git repository root
- Only use `-t uncommitted` for quick pre-commit spot checks

## Usage

When asked to run CodeRabbit or as part of pre-push review:

1. Ensure lint and tests pass (the `commit` skill's checklist, or the `lint` and
   `test` skills explicitly)
2. Run `coderabbit review --agent --type committed --base main` (background if needed)
3. Analyze findings; address critical/major issues
4. After fixes, run one verification pass if CodeRabbit had findings
5. Track run count (max 2–3 per change set)

Note: `-t committed` with `--base main` reviews the full branch diff. `-t uncommitted`
includes staged and unstaged changes (empty after a full commit with a clean tree).

## References

- [CodeRabbit CLI](https://www.coderabbit.ai/cli)
- [CLI reference](https://docs.coderabbit.ai/cli/reference.md)
