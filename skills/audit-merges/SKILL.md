---
name: audit-merges
description: >-
  Deep retrospective audit of everything merged to main over a window - code
  quality against the stand-* skills, introduced bugs, unsafe changes, merges
  over red signals, hollow thread resolutions, and untracked deferrals - with
  a tabbed HTML report as the deliverable. Use when asked to audit merges,
  review what landed on main, or verify automated/agent-authored merges were
  up to standard.
disable-model-invocation: true
---

# Audit Merges

Retrospective, read-only **code-substance audit** of every merge to `main`
across one or more repos over a time window. Where `sweep-prs` audits the PR
*lifecycle* (green builds, red main, thread hygiene), this skill re-reads the
**merged code itself** — quality, correctness, safety, and whether deferred
work was actually tracked. Built for high-automation repos where most merges
are agent-authored or auto-merged and human review coverage is thin.

## Invocation

- `/audit-merges` — current repo, last 7 days.
- `/audit-merges since 2026-07-22` — explicit window start; `7d` / `30d` /
  natural phrasing ("since last Wednesday") all work.
- `/audit-merges since 2026-07-22 lgtm-hq/py-lintro lgtm-hq/lgtm-ci` —
  explicit repo list. Invoked outside any repo with no repo argument → ask
  which repos, don't guess.

## Ground Rules

- **Read-only while auditing.** No pushes, no thread replies, no issue
  creation, no workflow triggers until findings are confirmed (Remediation).
- **Evidence or it didn't happen.** Every finding carries severity, PR
  link(s), concrete evidence (file:line, thread quotes, run IDs), and a
  recommended action. No speculative nitpicks — if you can't point at it,
  drop it.
- **Judge against the house standards.** Load the repo's matching standards
  skills before reading any diff: `stand-general` always, plus `stand-py` /
  `stand-rust` / `stand-ts` / `stand-odin` by language, `stand-ci` for
  workflow changes, and `analyze-code` for repo-shape risk emphasis.

## Phase 1 — Enumerate and triage

Per repo, gather in bulk with one paginated GraphQL `search` query per repo
(`type: ISSUE`, query `repo:OWNER/NAME is:pr is:merged merged:>=DATE`) whose
nodes fetch the checks rollup (`statusCheckRollup`) and review threads
(`reviewThreads`) in the same query — prefer server-side search filters over
client-side truncation. (The `sweep-prs` skill, where present, uses the same
recipe.)

1. Full merged-PR list for the window — paginate past 100; verify the total
   against `search(type: ISSUE)` `issueCount` (or the REST search API).
2. `main` workflow-run health across the window (`gh run list --branch main
   --created "START..END" --limit 1000` — an explicit date range plus a
   limit well above the repo's run volume; never the bare default, which
   returns a recent time-unbounded subset), so every failure can be mapped
   to the merge that caused it.

Then triage:

- **Bot PRs** (Renovate, release bots): light pass — merged green, `main`
  stayed green after. Exception: in repos whose *content* is the product
  (skills, configs, infra), also read what the bot changed.
- **Substantive PRs** (human- or agent-authored): full deep-read against the
  checklist below.

## Phase 2 — Deep-read checklist

Apply per substantive PR, diff in hand:

1. **Broken main, never fixed** — the merge caused a `main` failure and no
   later merge fixed it. Map every red `main` run to a cause and a
   resolution (or its absence).
2. **Quality regressions** — deviations from the loaded `stand-*` skills:
   workarounds, lint/type suppressions, inline shell in workflows, unpinned
   actions, dropped types, copy-paste drift, reduced maintainability.
3. **Merged over red signals** — failing or still-running required checks at
   merge time, or unresolved review threads from any reviewer (CodeRabbit,
   Greptile, CodeQL, humans).
4. **Hollow resolutions** — threads resolved with no fix and no reasoned
   disagreement, just closed to clear the gate (review-thread hygiene canon:
   resolve only via fix or disagreement reply).
5. **Unsafe changes** — secrets, token permissions, supply chain (unpinned
   deps/actions, new registries), script injection (`${{ }}` into `run:`),
   over-broad IAM, destructive CI or infra steps.
6. **Introduced bugs** — critical read of the diff: logic errors, unhandled
   error paths, off-by-ones, concurrency hazards, silently changed behavior.
7. **Untracked deferrals** — "follow-up", "later", "TODO", "out of scope",
   "in a separate PR" in code, PR body, or thread replies with **no
   corresponding issue filed**. Cross-check the repo's open issues; known
   intentionally-parked work is not a finding.
8. **Auditor's judgment** — anything else that should be addressed:
   convention breaks, doc drift, test assertions that assert nothing,
   coverage theater (`analyze-tests` mindset on PRs touching tests).

## Orchestration

Multi-repo audits fan out **one background sub-agent per repo**
(sub-agents-first). Each agent:

- loads that repo's standards skills (Ground Rules above),
- gathers per Phase 1, deep-reads per Phase 2,
- writes structured findings to a scratchpad file: stats header (total
  merges, bot/human split, `main` failure count), one section per finding
  (severity `critical/high/medium/low/info`, checklist category, PR links,
  evidence, recommended action), a "Clean" section of notable verified-fine
  PRs, and an overall verdict paragraph.

The orchestrator compiles the report only after all agents return; it never
duplicates their reading.

**Portability note:** on agents without background sub-agents, audit the
repos sequentially inline — same standards loading, gathering, deep-read,
and scratchpad findings file per repo — then compile the report the same
way. The fan-out is an optimization, not a prerequisite.

## Phase 3 — Report

The deliverable is a single self-contained HTML report (an Artifact when
available, else a local file):

- **One tab per repo**, plus a cross-repo executive summary tab leading with
  the verdict and top findings by severity.
- Per repo tab: stats header, `main`-health timeline, findings grouped by
  severity with expandable evidence and links, then the Clean list.
- Findings are written for a reader who didn't watch the audit: full
  sentences, no invented shorthand, every claim linked.

## Phase 4 — Remediate (checkpoint, confirmed only)

Checkpoint-then-execute (the same model `sweep-prs` uses, where present):
present aggregate counts with an assessment split (agree → propose
follow-up issue per the `issue` skill; disagree/moot → propose disposition
reply; no-action → one-line rationale),
let the owner approve per bucket, then execute exactly what was confirmed.
Never trade the checkpoint away for fewer clicks.

## Notes

- Complement, not replacement: `sweep-prs` is the cheap wide lifecycle
  sweep; `audit-merges` is the expensive deep substance read. Run the sweep
  more often, the audit periodically or after high-automation bursts.
- Overlap between windows is harmless — previously remediated findings
  assess as already-dispositioned.
- Origin: manual multi-repo audit of 2026-07-22 → 2026-07-27 merges across
  six lgtm-hq repos (~413 merges), prompted by agent-authored auto-merged
  work having effectively gone unreviewed by a human.
