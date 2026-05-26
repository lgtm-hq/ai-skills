---
name: review
description: Run CodeRabbit to review code changes. Use when asked to review code, get feedback, or analyze changes. Max 3 runs per change set.
---

# Review

Run CodeRabbit to review code changes.

## Relationship to analyze-* skills

The `analyze-code`, `analyze-project`, and `analyze-tests` skills are for
**manual or agent-driven pre-review checks**—they run concrete commands (lintro,
ripgrep, coverage, etc.) and produce structured findings before you open a PR.

This `review` skill uses **CodeRabbit** for automated diff review. Do not duplicate
full analyze rubrics here; use analyze-* skills when you need deep, command-backed
analysis of the whole codebase or test suite.

## Commands

- `cr -h` - Show CodeRabbit help
- `coderabbit --prompt-only -t committed --base main` - Review full branch diff against
  main (matches CI behavior)
- `coderabbit --prompt-only -t uncommitted` - Review only uncommitted/unstaged changes
  (quick local check)

## Rules

- IMPORTANT: Do NOT run CodeRabbit more than 3 times for a given set of changes
- Always use the `--prompt-only` flag
- **Default to `--base main`** — this matches CI and catches the full branch diff
- Only use `-t uncommitted` for quick pre-commit spot checks

## Usage

When asked to review code:

1. Run `coderabbit --prompt-only -t committed --base main` to review the full branch
   diff against main
2. Analyze the review output
3. Address any issues identified
4. Track the number of review runs (max 3 per change set)

Note: `-t uncommitted` only sees unstaged changes, which is empty after a commit.
Using `--base main` matches what CI sees and catches issues across the entire change
set.
