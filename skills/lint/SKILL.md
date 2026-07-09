---
name: lint
description: >-
  Run linting and formatting. Prefer `uv run lintro chk` for checks and
  `uv run lintro fmt` for formatting when lintro is available; fall back to native
  tools only when lintro is unavailable or another skill documents a follow-up pass
  (e.g. raycast).
---

# Lint

## Tooling

Prefer [lintro](https://github.com/lgtm-hq/py-lintro) for linting and formatting.
When available, use `uv run lintro chk` and `uv run lintro fmt`.

If lintro is unavailable, fall back to the language's native bundled tools (ruff,
black, clippy, rustfmt, eslint, bandit, etc.). Another skill may document an
additional pass after lintro (for example, `raycast` runs `npm run lint` after
lintro — Raycast rules take precedence for extension-specific checks).

## Commands

- `uv run lintro fmt` — format code
- `uv run lintro chk` — check code for issues
- `uv run lintro tst` — run tests

## Rules

- **CRITICAL: NEVER run `lintro chk --tools ...` (targeted/filtered checks).** Always run
  the full `uv run lintro chk` without `--tools`. Filtered runs silently skip tools and
  miss issues.
  - **Exception:** single-tool runs (`--tools <tool>`) are permitted only when
    developing or verifying that specific lintro tool (the `/lintro-add` and
    `/lintro-verify` workflows). Even then, a full `uv run lintro chk` is still
    required before committing.
- Linting must produce **zero issues** before proceeding
- **Fix ALL issues** — whether introduced in the current session or pre-existing
- **Ignore policy** — suppressing a finding is not a fix:
  1. **Fix the root cause first.** `# noqa`, `# type: ignore`, `# nosec`,
     `# nosemgrep`, `# yamllint disable-line`, etc. are a LAST resort, only
     when there is no reasonable fix.
  2. **If suppression is genuinely required**, use the narrowest possible
     ignore — specific rule code, single line — WITH an inline justification
     comment (`# nosec B603 - fixed argv list, no shell`). Unjustified
     ignores are rejected.
  3. **Blanket or file-level ignores** (whole-file disables, config-wide
     excludes) require a documented exception (e.g. in `CONTRIBUTING.md`).

## Usage

When asked to lint or format code:

1. Run `uv run lintro fmt` FIRST to auto-fix formatting issues across the ENTIRE
   codebase (when lintro is available)
2. Run `uv run lintro chk` to check for remaining issues (when lintro is available)
3. If lintro is unavailable, use native tooling for the language and still aim for
   zero issues
4. Manually fix any issues found — do not leave issues unfixed
5. Re-run the check command to verify all fixes
6. Only as a last resort, add ignore comments WITH justification
