---
name: stand-general
description: Global coding standards for all projects and languages. Use when writing any code. Covers linting with lintro, testing with coverage, semantic commits, PR creation, and code review with cr (CodeRabbit CLI).
---

# Coding Standards

Global standards that apply to all projects and languages.

## Single Source of Truth

Any value defined in one place and consumed in another should be referenced, not copied.
Applies to versions, paths, URLs, schema constants, and configuration.

- If two files would need to be updated in lockstep, the second is a derived artifact —
  generate it, don't hand-maintain it.
- CI verification of two files agreeing is a smell: the right pattern is
  run-the-generator + `git diff --exit-code`, not parse-and-compare.
- Hand-maintained mirrors of canonical sources rot silently. The cost of a small
  generator is always lower than the cost of recurring drift bugs.

## Cross-cutting References

- Linting and formatting: see `/lint`
- Ignoring lint issues: see `/lint` (Rules section)
- Testing: see `/test`
- Commits: see `/commit`
- Pull requests: see `/pr`
- Code review: see `/review`
