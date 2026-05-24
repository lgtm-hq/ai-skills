---
name: lint
description: >-
  Run linting and formatting with lintro. Use `uv run lintro chk` for checks and
  `uv run lintro fmt` for formatting. Do not run bundled native tools directly
  unless another skill explicitly overrides (e.g. raycast).
---

# Lint

## Tooling

All linting and formatting MUST go through [lintro](https://github.com/lgtm-hq/py-lintro).
Do not invoke bundled native tools directly (ruff, black, clippy, rustfmt, eslint,
bandit, etc.) unless another skill in this repository explicitly documents an
override (for example, `raycast` uses `ray lint`).

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
   codebase
2. Run `uv run lintro chk` to check for remaining issues
3. Manually fix any issues found — do not leave issues unfixed
4. Re-run `uv run lintro chk` to verify all fixes
5. Only as a last resort, add ignore comments WITH justification
