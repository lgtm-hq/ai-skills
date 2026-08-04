---
name: backlog
description: >-
  Interactive dispatcher for backlog work. Asks one routing question — drive
  PRs to merge, or implement issues to open-PR state — then follow-ups based
  on the answer, and hands off to implement-issues / babysit-pr with standing
  policy applied. Use when asked to work the backlog or run /backlog.
disable-model-invocation: true
---

# Backlog

Route a backlog session to the right workflow via a short interview, then
dispatch to `implement-issues` and/or `babysit-pr`. This skill decides and
delegates — it implements nothing itself.

## Invocation

- `/backlog` — run the interview below.
- Args answer questions in advance; skip any question already answered:
  - `/backlog merge` / `/backlog open-pr`
  - `/backlog merge #124 #125` — explicit PR list
  - `/backlog open-pr #12 #14` — explicit issue list

## Interview

Ask with structured multiple-choice questions (AskUserQuestion in Claude
Code; plain questions elsewhere). One round per step — this is a router,
not a grilling.

### Q1 — Goal

> What should this session drive toward?

- **merge-pr** — take PRs (and optionally fresh issues) all the way to
  merged, releases included.
- **open-pr** — implement issues and stop at merge-ready open PRs; the
  human merges.

### Q2 — branch on the answer

**If merge-pr:**

> What's in scope?

- **All open PRs** in the repo (default).
- **Specific PRs** — take the list from args or ask.
- **Issues first, then all PRs** — run `implement-issues` on issues without
  PRs, then babysit everything open.

**If open-pr:**

> Which issues?

- **All open issues without a PR** (default).
- **Specific issues** — take the list from args or ask.

Do not ask about repo (use the current checkout), sub-agents, lint, or
release handling — those are fixed by standing policy below.

### Q3 — Plan confirmation (deliberate, keep it)

The interview scopes the session; it does **not** replace the composed
skills' own confirm steps. After triage, present the concrete plan — the
issue/PR set, any surprises found (stale issues, no-PR-shaped work,
orphaned branches), and any decision the issues themselves reserve for the
owner — and confirm before spawning lanes. The owner wants to be in the
loop on judgment calls the workflow would otherwise assume; never trade
this checkpoint away for fewer clicks.

## Routing

- **merge-pr** → for the issues-first variant, run the `implement-issues`
  skill to open PRs, then run the `babysit-pr` skill with `--merge` across
  the in-scope PRs (one babysitter for all of them, per that skill's
  guidance). Otherwise go straight to `babysit-pr --merge`.
- **open-pr** → run the `implement-issues` skill, then run the `babysit-pr`
  skill **without** `--merge` across the resulting PRs (one babysitter for
  all of them, per that skill's guidance) until Phase 5 exit conditions hold
  (threads resolved, checks green). Report PR URLs and stop — never merge in
  this mode.

Read and follow the composed skills at dispatch time; do not restate their
workflows here.

## Standing policy (applies to every route)

- **Red `main` is P0.** If `main` is or goes red at any point: pause the
  current lane, file an issue (per the `issue` skill), fix it on a branch
  (per the `pr` skill), babysit that PR first, then resume.
- **Assess before amplifying.** When babysitting PRs you did not implement
  in this session, review the implementation on its merits; where you
  disagree, fix or push back on the PR rather than shepherding it through
  unchanged.
- **CodeRabbit rate limits do not block exit** — now the `babysit-pr` Step E
  default; no override needed.
- **Releases**: follow the composed skills' release handling (1 PR = 1
  release where that is the repo convention).
- **Sub-agents**: run lanes and babysitters as background sub-agents so the
  main thread stays free, where the harness supports it.

## Final report

Whatever the route, end with: PRs opened, PRs merged (or n/a), releases
merged, blocked lanes with reasons, and any pending human gates.
