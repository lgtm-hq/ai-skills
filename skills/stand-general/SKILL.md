---
name: stand-general
description: Global coding standards for all projects and languages. Use when writing any code. Covers linting with lintro, testing with coverage, semantic commits, PR creation, and code review with CodeRabbit.
---

# Coding Standards

Global standards that apply to all projects and languages.

## Linting

- All linting MUST be done with `lintro`
- Available commands: `lintro fmt`, `lintro chk`, `lintro tst`
- Native tools should NOT be used directly

## Single Source of Truth

Any value defined in one place and consumed in another should be referenced, not copied. Applies to versions, paths, URLs, schema constants, and configuration.

- If two files would need to be updated in lockstep, the second is a derived artifact — generate it, don't hand-maintain it.
- CI verification of two files agreeing is a smell: the right pattern is run-the-generator + `git diff --exit-code`, not parse-and-compare.
- Hand-maintained mirrors of canonical sources rot silently. The cost of a small generator is always lower than the cost of recurring drift bugs.

## Ignoring Issues

- Ignoring issues is NOT permitted unless it's the absolute last resort and completely justified
- This includes docstrings for tests - they are still required
- When an ignore IS applied, a comment MUST explain why:
  ```python
  # Ignore: Third-party library returns untyped data
  value: Any = external_lib.get_data()  # type: ignore[no-untyped-call]
  ```

## Testing

- Test runs should ALWAYS generate a coverage report
- New code requires new tests
- Code changes require updated tests

## Commits

Pre-commit requirements:
1. All linting must pass (`lintro chk`)
2. All tests must pass (`lintro tst`)
3. Docker builds must pass (where applicable)

Commit rules:
- Every commit must be signed/verified (`git commit -S`)
- Use semantic prefixes: `fix:`, `feat:`, `chore:`, `docs:`, `refactor:`, `test:`, `build:`, `ci:`, `perf:`, `style:`
- Use imperative mood ("Add feature" not "Added feature")

## Pull Requests

- Use the PR template from the current repository
- Assignees/labels are managed by CI and PR-workflow docs for the repository

## Code Review

- Use CodeRabbit with `--prompt-only` flag
- For uncommitted changes: `coderabbit --prompt-only -t uncommitted`
- LIMIT: Maximum 3 CodeRabbit runs per change set

## Language-Specific

See also:
- `/stand-py` - Python >= 3.11 standards
- `/stand-ts` - TypeScript/JavaScript standards
