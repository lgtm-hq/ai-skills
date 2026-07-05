---
name: greptile
description: >-
  Run Greptile CLI for pre-push AI branch review. Use when asked for Greptile review,
  raycast/extensions pre-PR checks, or as part of the default dual pre-push workflow
  with coderabbit. Max 2 runs per change set.
---

# Greptile CLI Review

Run **Greptile** (`greptile`) for automated branch review before push. Pair with
**`coderabbit`** for the default pre-CI workflow — both tools catch different issues
and mirror CI.

## Relationship to analyze-* skills

The `analyze-code`, `analyze-project`, and `analyze-tests` skills are for
**manual or agent-driven pre-review checks**—they run concrete commands (lintro,
ripgrep, coverage, etc.) and produce structured findings before you open a PR.

This skill uses **Greptile CLI** for external AI branch review. Follow the `lint` and
`test` skills (or the `commit` skill, which includes them) before invoking Greptile.
Do not duplicate full analyze rubrics here.

## Relationship to coderabbit

Default pre-push flow when CI runs both tools:

```text
commit → [greptile ‖ coderabbit] → pr
```

Each step names the skill to follow.

Run **greptile** and **coderabbit** in parallel (`‖`) when possible. Greptile is typically
faster (~1 min). Do not re-run on unchanged code.

## Prerequisites

```bash
greptile login
greptile whoami
```

Install: `npm i -g greptile` or see [Greptile CLI](https://www.greptile.com/cli).

## Commands

- `greptile review -b main --agent` — Review current branch vs main (default for agents)
- `greptile review --diff` — Findings inline with relevant code
- `greptile review --json` — Machine-readable output (use instead of `--agent` for parsing)
- `greptile review --resume` — Continue the latest unfinished review
- `greptile review show [ID]` — Reopen a past review

`--agent` is an alias for `--text` (plain text, not JSON). Use `--json` when a tool
needs structured output.

## Rules

- Max **2** Greptile runs per change set (workflow discipline)
- **Commit before running** — Greptile reviews branch commits vs base; uncommitted
  changes are ignored
- **Default to `-b main`** unless the repo uses a different default branch
- Run from the repository root on the feature branch

## Usage

When asked to run Greptile or as part of pre-push review:

1. Ensure changes are committed and lint/tests pass
2. Run `greptile review -b main --agent` (can run parallel with CodeRabbit)
3. Analyze findings; address critical/major issues
4. After fixes to Greptile-sensitive areas, optional verification pass
5. Track run count (max 2 per change set)

For Raycast extension PRs, run static greps from `pr-raycast` before the CLI review.

## Differences from CodeRabbit

|              | CodeRabbit                           | Greptile                                              |
| ------------ | ------------------------------------ | ----------------------------------------------------- |
| Scope        | `all` / `committed` / `uncommitted`  | Branch commits vs base only                           |
| Agent output | `--agent` → JSON stream              | `--agent` → plain text; `--json` for machine-readable |
| Base branch  | `--base main`                        | `-b main`                                             |

## References

- [Greptile CLI](https://www.greptile.com/cli)
- [CLI reference](https://www.greptile.com/docs/code-review/greptile-cli.md)
