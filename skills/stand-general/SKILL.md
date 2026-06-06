---
name: stand-general
description: Global coding standards for all projects and languages. Use when writing any code. Covers linting with lintro, testing with coverage, semantic commits, PR creation, and pre-push AI review with coderabbit and greptile CLIs.
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
- Pre-push AI review (CodeRabbit): see `/coderabbit`
- Pre-push AI review (Greptile): see `/greptile`

## Pre-push review workflow

CLI review mirrors CI and catches issues before slow CI completes. Default: run
**both** Greptile and CodeRabbit when CI uses both.

**Short flow:**

```text
/commit → /greptile → /coderabbit → /pr
```

**Explicit flow:**

```text
/lint → /test → /commit → /greptile → /coderabbit → /pr
```

Run greptile and coderabbit in parallel when possible. Fix findings, then optional
verify pass. Do not re-run either CLI on unchanged code. CI remains the merge-time
confirmation.
