---
name: stand-general
description: Global coding standards for all projects and languages. Use when writing any code. Covers linting with lintro, testing with coverage, semantic commits, PR creation, and pre-push AI review with coderabbit, greptile, and lintro review CLIs.
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

## Before You Write

Before implementing utility logic (file traversal, string parsing, config lookup,
error wrapping), search the codebase for an existing implementation.

- Found a close match? Import or extend it instead of reimplementing.
- Same pattern already in 2+ files? Extract it to a shared module before adding
  a third instance.
- Duplication accumulates one compliant PR at a time — prevent it at writing time
  rather than relying on later audits.

## Pre-Implementation

Answer three questions before creating a new file, module, or significant function:

1. **Does this logic already exist?** Search first; reuse beats rewrite.
2. **Is this the right module?** An existing module growing too large is a signal
   to refactor it, not to create a parallel module beside it.
3. **Will this create duplication later?** If similar future cases are foreseeable,
   put the logic in a shared location from the start.

## Architectural Awareness

When adding a module or significant function:

- Confirm it fits the layer it lives in, and that its dependency direction matches
  the existing architecture.
- Every new dependency arrow between modules must be intentional — never a
  side effect of convenient imports.
- A module growing past ~300–400 lines is a signal to split it along
  responsibility boundaries.

## Dependency Update Triage (Renovate/Dependabot)

- **Merge safe green bumps.** For breaking major bumps, fix and migrate —
  never just close the PR to dodge the work.
  - Don't: close a failing Astro 6→7 Renovate PR because `@astrojs/tailwind`
    no longer builds.
  - Do: migrate to the replacement (`@tailwindcss/vite`) in the same PR, then
    merge.
- **Green doesn't mean safe.** On a repo where CI doesn't cover every path, a
  green PR can still be broken in the un-CI'd parts. Validate those parts
  locally before merging, not just the parts CI checks.
- Backlog handling for dependency issues/PRs (closing, repurposing,
  announcing changes): follow the `issue` skill's Backlog Stewardship section.
- **Prefer the bot's own PR.** Digest and version follow-ups that Renovate or
  a release bot will open are merged from that PR, not re-created by hand; see
  **Authority boundaries** below.
- Clearing a whole backlog of updates: follow the `catch-up-deps` skill.

## Authority boundaries

Some decisions belong to the owner, however obvious the fix looks. Unless the
owner granted it explicitly for the task at hand:

- **Gate configuration.** Never add, remove or relax a CI gate, skip allowlist,
  toleration, lint suppression or vulnerability ignore. Removing an entry that
  looks stale counts too. Report what the gate caught and propose the change;
  the owner decides. The one exception is a vulnerability suppression
  reassessed inside a dependency catch-up the owner asked for, and each of
  those carries a reason, an expiry and an issue link.
- **Issues.** Filing an issue that the owner's instructions or the repo's
  standing policy already call for (red `main`, a babysit blocker) is fine.
  Filing one to record your own finding or design proposal is not: say it in a
  sentence and let the owner decide whether it becomes backlog.
- **Bot-owned pull requests.** When a bot will open the PR (Renovate digest
  bumps, release version PRs, tap bumps), merge the bot's PR rather than
  hand-rolling a copy. Close stale bot PRs with a pointer to the one that
  supersedes them instead of merging old ones.
- **Publish gates and environments.** Human gates by default. With an explicit
  grant, approve only what the owner named, one in flight per environment, and
  stop at the first failure.
- **Holds.** Work the owner put on hold stays untouched until they lift it,
  even when it sits next to what you are doing.

When unsure whether a decision is yours, ask before acting. A correct change
made without authority is still a violation. Consumers: `babysit-pr`,
`backlog`, `implement-issues`, `catch-up-deps`.

## Per-repo agent context (`AGENTS.md` / `CLAUDE.md`)

Every target repo may carry a standing context file that assessment and
implementation skills load automatically. **Precedence:** if both
`AGENTS.md` and `CLAUDE.md` exist, `AGENTS.md` is authoritative — apply it
and do not also apply conflicting `CLAUDE.md` instructions. If only one
exists, use that file. If both exist and their requirements conflict in a
way that blocks safe progress, stop and ask the user which wins rather than
guessing. When present, treat its standards, constraints, and contract as
**binding** for the session — do not re-type them from chat memory.

### Expected sections

Write the file so the **per-repo delta is only the repo facts**. Put recurring
org-wide rules in an org preset section (or point at a shared org doc) rather
than copying them into every repo.

1. **House standards pointers** — toolchains (e.g. `uv` / `bun` / `lintro`),
   lint entry point, CI source / reusable workflows, model repos to copy
   conventions from, and any org-managed ruleset notes.
2. **Contract / operating agreement** — autonomy level, merge policy (who
   merges, squash vs queue, signed commits), babysit/review expectations, and
   how the agent should surface vs keep going.
3. **Standing constraints** — safety limits (e.g. no paid LLM API calls during
   assessment), scope rules, storage limits (e.g. local SQLite only), and
   no-side-effects rules for assessment-only work.
4. **Org preset** — recurring org-wide rules referenced once so each repo file
   stays short; only repo-specific product/org facts belong outside this
   section.

### Consumers

At start of a run, these skills read the target repo's `AGENTS.md` /
`CLAUDE.md` when present and apply it as binding context:

- `analyze-project`
- `implement-issues`
- `babysit-pr`

Missing the file is fine — fall back to chat instructions and `stand-*`
skills. Do not invent standing constraints that are not in the file or the
user's message.

## Cross-cutting References

- Linting and formatting: follow the `lint` skill
- Ignoring lint issues: follow the `lint` skill (Rules section)
- Testing: follow the `test` skill
- Commits: follow the `commit` skill
- Pull requests: follow the `pr` skill
- Pre-push AI review (CodeRabbit): follow the `coderabbit` skill
- Pre-push AI review (Greptile): follow the `greptile` skill
- Pre-push AI review (lintro): follow the `lintro-review` skill
- Per-repo standing context: see **Per-repo agent context** above

## Pre-push review workflow

CLI review mirrors CI and catches issues before slow CI completes. Default: run
**all three** Greptile, CodeRabbit, and lintro review where available (owner
policy, 2026-08-02). When Greptile/CodeRabbit are rate-limited, do not wait — the
lintro pass is the review of record for the push.

**Short flow:**

```text
commit → [greptile ‖ coderabbit ‖ lintro-review] → pr
```

**Explicit flow:**

```text
lint → test → commit → [greptile ‖ coderabbit ‖ lintro-review] → pr
```

Each step names the skill to follow.

`‖` means run greptile, coderabbit, and lintro-review in parallel when possible. Fix
findings, then optional verify pass. Do not re-run any CLI on unchanged code. CI
remains the merge-time confirmation.
