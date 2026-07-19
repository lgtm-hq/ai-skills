---
name: backlog
description: >-
  Interactive dispatcher that routes a backlog session to implement-issues and/or
  babysit-pr via a short interview. Applies standing policy (red-main P0, assess
  before amplifying, CodeRabbit rate-limit override) before spawning lanes. Use
  when asked to work the backlog, run a backlog session, or dispatch issues and PRs.
disable-model-invocation: true
---

# Backlog

Interactive routing entry point for backlog sessions. Ask two questions, confirm
the plan, then delegate — never re-implement what `implement-issues` or `babysit-pr`
already specify.

## Invocation

Args skip already-answered questions:

- `/backlog` — start the full interview (Q1 → Q2 → Q3).
- `/backlog merge #124 #125` — goal = `merge-pr`, scope = those PRs; jump to Q3.
- `/backlog open-pr` — goal = `open-pr`, scope TBD; start at Q2.
- `/backlog open-pr all` — goal = `open-pr`, scope = all eligible; jump to Q3.

## Interview

### Q1 — Goal

> **What is the goal for this session?**
>
> 1. `merge-pr` — shepherd open PRs to merged (drive existing PRs to `main`).
> 2. `open-pr` — implement open issues and open PRs (stop at PR-open, no merge).

Wait for an answer (or read from args).

### Q2 — Scope

> **Which issues / PRs are in scope?**
>
> 1. All eligible (let triage decide).
> 2. Specific list — provide issue/PR numbers.

Wait for an answer (or read from args).

### Q3 — Plan confirmation (deliberate, keep it)

After running triage (see Standing policy — P0 check, then `gh issue list` /
`gh pr list`), present:

- The concrete set of issues/PRs you intend to act on, in proposed order.
- Any **surprises** found during triage (unexpected red `main`, locked signing,
  stale PRs, missing AI Implementation Prompts, etc.).
- **Owner-reserved decisions** that need a yes/no before lanes are spawned (e.g.
  "Issue #312 overlaps PR #309 — implement separately or bundle?").

**Wait for explicit confirmation before spawning any lane or merge operation.**

This checkpoint is deliberate: it keeps the owner informed before automation runs.
It does not replace the confirm steps inside `implement-issues` or `babysit-pr` —
those run independently per their own skill files.

## Routing

Route based on the confirmed goal. Follow the composed skill by reference — never
re-state its full workflow here.

### `merge-pr`

1. If issues are in scope: delegate to `implement-issues` first.
2. Delegate open PRs to `babysit-pr --merge`.

### `open-pr`

1. Delegate issues to `implement-issues`.
2. Delegate any already-open PRs to `babysit-pr` (without `--merge`).

## Standing policy

Apply these before Q3 confirmation and carry them into every composed skill invocation.

### Red `main` is P0

Before routing to any lane, check `main` CI health:

```bash
gh run list --branch main --limit 5 --json conclusion,status,name
```

If `main` is red: open an issue, implement a fix PR, babysit it to merge — **before**
touching anything else in the backlog. Report the blocker at Q3.

### Assess before amplifying

If the backlog is large, prefer a focused set over a full sweep. Do not spawn 20 lanes
when 5 high-value issues exist. Triage selects self-contained, file-disjoint, AI
Implementation Prompt-ready issues first.

### CodeRabbit rate-limit override

This session authorises `babysit-pr` to exit successfully when all other Phase 5
conditions are met and the only remaining blocker is a CodeRabbit rate-limit window
**without any unreviewed current-head commit** (i.e. the current head is already
reviewed; the wait is for a follow-up review after a trivial fixup). Do not sleep
indefinitely on the rate limit in that case — note it in the final report and exit.

If the current head is **unreviewed**, the standard `babysit-pr` Step E behavior
applies: post `@coderabbitai please review` and wait.

Note: issue #261 may flip the `babysit-pr` default later; until then this override
is carried by `backlog`.

### Releases

Release PR handling is deferred entirely to `babysit-pr`. Do not attempt to manage
publish gates or version PRs from this skill.

### Background sub-agents

When the harness supports background sub-agents, spawn lanes as background tasks so
the main thread stays free for monitoring and owner Q&A.

## Final report

After all lanes complete, return:

| Field | Value |
| --- | --- |
| Goal | merge-pr / open-pr |
| Scope | issues / PRs acted on |
| PRs opened | list with URLs (open-pr mode) |
| PRs merged | list (merge-pr mode, or n/a) |
| Blocked lanes | reason per lane |
| `main` health | green / was-red-fixed / still-red |
| Human actions needed | approvals, decisions, publish gates |
