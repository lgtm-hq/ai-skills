---
name: sweep-prs
description: >-
  Retrospective audit of recently merged/closed PRs for anomalies that slipped
  through - merges without green builds, merges onto red main, unresolved or
  post-merge review threads, hollow resolutions. Read-only sweep, then
  confirmed remediation (issues, disposition replies). Use when asked to sweep
  PRs, audit merged PRs, or check what slipped through.
disable-model-invocation: true
---

# Sweep PRs

Audit recently merged and closed PRs for anomalies that slipped through the
normal PR lifecycle. Two strictly separated phases: a **read-only sweep**
that gathers evidence, then **confirmed remediation**. Never mutate anything
(issues, replies, resolutions) before the findings are confirmed.

## Invocation

- `/sweep-prs` — current repo, last 14 days. Each sweep is stateless: no
  memory of previous runs, by design — pass an explicit window to change
  scope.
- `/sweep-prs 4d` / `/sweep-prs 30d` / `/sweep-prs since 2026-07-01` —
  explicit window; natural phrasing ("last 4 days") is fine too.
- `/sweep-prs lgtm-hq/podex lgtm-hq/py-lintro` — explicit repos (default:
  current checkout's repo, via `gh repo view`).
- **No checkout needed**: all gathering uses `gh api` with explicit
  `owner/repo`, so explicit-repo invocations work from any directory;
  without a local checkout, verify claims via API file reads instead of
  `git show origin/main:`. Invoked outside any repo with no repo argument
  → ask which repo, don't guess.

## Phase 1 — Gather (read-only)

Enumerate merged and closed PRs in the window (`gh pr list --state merged` /
`--state closed`, GraphQL for thread state).

**Gather in bulk, not per-PR.** Paginated GraphQL search (~25 PRs/page,
fetching checks rollup + review threads + reviews in one query) covers
hundreds of PRs in a handful of API calls; analyze the dump locally
(`jq`). Reserve background sub-agents for Phase 2's per-finding
assessment deep-reads, in batches of ~5 PRs each — read-only: no writes,
no replies, no issue creation. Use server-side filters where they exist
(e.g. `actions/runs?status=failure` for Check B) — client-side filtering
of `gh run list` output silently truncates at the fetch limit.

### Check A — Merged without green builds

For each merged PR, compare check-run conclusions on the merge commit
(head SHA) against the merge timestamp:

- Any required check `FAILURE` / `TIMED_OUT` / still running at merge time.
- Checks that never ran on the final head (stale approvals, admin bypass).
- `CANCELLED` runs are usually superseded duplicates, not failures — verify
  before flagging.

For each hit: was the failure addressed post-merge (follow-up commit on
`main`, existing issue)? Record addressed/unaddressed.

### Check B — Merged while main was red

Reconstruct `main`'s workflow-run health over the window (`gh run list
--branch main`). For each merge that landed inside a red window: did the
merge fix the redness, ignore it, or worsen it? Was the red-main cause
tracked in an issue? Record.

### Check C — Review threads (all reviewers)

For every merged/closed PR, via GraphQL:

- **Unresolved threads** from any reviewer — CodeRabbit, Greptile, Bugbot,
  github-advanced-security/CodeQL, humans.
- **Post-merge reviews**: reviewer activity timestamped *after* the merge —
  the in-flight-review race (see `babysit-pr`'s merge-gate rule: zero
  threads is not evidence of review). These are invisible to normal PR
  hygiene and must be surfaced explicitly.
- **Hollow resolutions**: threads resolved with no reply and no linked fix —
  per review-thread hygiene canon, resolve only via a fix or a disagreement
  reply.
- **Closed-not-merged PRs** with dangling unresolved threads (superseded
  PRs whose findings were never carried to the successor).

### Check D — Case-by-case checklist (extensible)

A living list — add checks here as new anomaly patterns are observed rather
than keeping them in chat memory:

- Admin/bypass merges (`--admin`, branch-protection overrides) without a
  recorded justification.
- PRs closed without any comment explaining why.
- Repo-convention adherence where applicable (e.g. 1 PR = 1 release: change
  PRs merged without their release PR).
- Version/lockfile drift introduced by a merge and not followed up.

## Phase 2 — Assess, summarize, then confirm (checkpoint, deliberate)

Before presenting anything, **assess every finding on its merits** — read
the thread/failure against current `main` and take a position:

- **Agree** (real, still stands) → propose a follow-up issue (per the
  `issue` skill, with AI Implementation Prompt when code-shaped).
- **Disagree / moot / already addressed** → propose a disposition reply +
  resolve (link the fixing commit/PR; no hollow resolutions).
- **No action**, with one line of rationale (recorded in the report).

Then present a **summary first, details on demand** — aggregate counts
with the assessment split, not per-item detail. The shape:

> Found N unresolved threads and M hollow-resolved ones. Of the
> unresolved, I agree with X (propose follow-up issues) and disagree
> with Y (propose reply + resolve). Of the resolved, Z look wrongly
> resolved and deserve reopening or a follow-up issue.

Do **not** lead with what each individual finding was. The owner then
chooses per bucket: approve the batch, drill into any subset item by item
before deciding, or skip. Per-item detail (PR, severity, evidence,
timestamps, links) is produced only when asked, and kept ready from
Phase 1 so drill-down is instant.

Confirmation rules: the checkpoint is deliberate — never trade it away
for fewer clicks. Questions must be self-contained and answerable without
scrolling back: no invented codenames ("F1", "finding 3") pointing at
earlier tables; each option states what-was-found and what-will-happen in
its own words. No-action findings are report rows, never options. Batch
approval is fine when the owner says so.

## Phase 3 — Remediate (only what was confirmed)

Execute exactly the confirmed dispositions: file issues, post replies,
resolve threads. Follow the `issue` skill's backlog-stewardship rules
(announce changes, comment before closing, no silent churn).

## Final report

Per repo: PRs swept (count, window), findings by check with disposition
(issue filed / replied+resolved / no-action+rationale), issues created
(URLs), and anything deferred with reason. The report is the sweep's only
output — sweeps keep no state between runs; overlap between windows is
harmless because remediated findings assess as already-dispositioned.

## Notes

- This is the periodic, fleet-wide complement to `babysit-pr`'s per-PR
  post-merge sweep backstop — that one catches the race on PRs it just
  merged; this one catches everything else, including sessions that didn't
  use the skills at all.
- Origin: recurring manual ritual of eyeballing every merged PR's diff and
  threads across repos (2026-07-19; found podex#255/#262 post-merge
  CodeRabbit findings, incl. an unread Critical).
