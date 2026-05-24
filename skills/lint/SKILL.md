---
name: lint
description: >-
  Run linting and formatting. Prefer `uv run lintro chk` for checks and
  `uv run lintro fmt` for formatting when lintro is available; fall back to native
  tools only when lintro is unavailable or another skill explicitly overrides
  (e.g. raycast).
---

# Lint

## Tooling

Prefer [lintro](https://github.com/lgtm-hq/py-lintro) for linting and formatting.
When available, use `uv run lintro chk` and `uv run lintro fmt`.

If lintro is unavailable, fall back to the language's native bundled tools (ruff,
black, clippy, rustfmt, eslint, bandit, etc.). Another skill in this repository
may also explicitly document an override (for example, `raycast` uses `ray lint`).

## Commands

- `uv run lintro fmt` — format code
- `uv run lintro chk` — check code for issues
- `uv run lintro tst` — run tests

## Rules

- Linting must produce **zero issues** before proceeding
- **Fix ALL issues** — whether introduced in the current session or pre-existing
- **Ignoring issues is a LAST resort** — only use `# noqa`, `# type: ignore`,
  `# nosec`, `# yamllint disable-line`, etc. when there is no reasonable way to
  fix the issue
- **Justification required for ignores** — any ignore comment MUST include an
  explanation of why the ignore is necessary (e.g., `# nosec B604 - not a
  subprocess call, just a dataclass field named 'shell'`)

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
