---
name: lint
description: "Run linting and formatting with lintro. Use when asked to lint, format, or check code quality. Commands: lintro fmt, lintro chk, lintro tst."
---

# Lint

Run linting commands using lintro.

## Commands

- `uv run lintro fmt` - Format code
- `uv run lintro chk` - Check code for issues
- `uv run lintro tst` - Run tests

## Rules

- All linting should be done with lintro only
- Native tools (ruff, black, mypy, etc.) should NOT be used directly
- Linting with lintro should have zero issues before proceeding
- **Fix ALL issues** - whether they were introduced in the current session or
  pre-existing
- **Ignoring issues is a LAST resort** - only use `# noqa`, `# type: ignore`, `# nosec`,
  `# yamllint disable-line`, etc. when there is no reasonable way to fix the issue
- **Justification required for ignores** - any ignore comment MUST include an
  explanation of why the ignore is necessary (e.g., `# nosec B604 - not a subprocess
call, just a dataclass field named 'shell'`)

## Usage

When asked to lint or format code:

1. Run `uv run lintro fmt` FIRST to auto-fix formatting issues across the ENTIRE
   codebase
2. Run `uv run lintro chk` to check for remaining issues
3. Manually fix any issues found - do not leave issues unfixed
4. Re-run `uv run lintro chk` to verify all fixes
5. Only as a last resort, add ignore comments WITH justification
