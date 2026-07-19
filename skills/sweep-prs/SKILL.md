---
name: sweep-prs
description: >-
  Retrospective audit of merged and closed PRs over a time window. Surfaces
  merged-without-green-builds, unresolved review threads, post-merge redness,
  and admin-bypass patterns. Produces a findings table, gets owner confirmation,
  then remediates: opens fix-forward issues, posts dispositions, resolves
  threads. Use when asked to sweep PRs, audit recent merges, or run a
  retrospective PR health check.
disable-model-invocation: true
---

# Sweep PRs

Retrospective, read-then-confirm-then-fix audit of a repository's recently
merged and closed pull requests. Work in four phases: gather evidence
(read-only), present a findings checkpoint, remediate only confirmed items,
then produce a final report.

## Invocation

- `/sweep-prs` — sweep the last **14 days** (default window)
- `/sweep-prs 30d` — last 30 days
- `/sweep-prs 7d` — last 7 days
- `/sweep-prs since 2026-06-01` — on or after an ISO date
- `Sweep PRs from the last two weeks on owner/repo` — natural language; explicit
  `owner/repo` works from any directory
- `Sweep PRs` (outside any repo, no argument) — ask for the target repository
  before proceeding

**Stateless by design.** No tracking issues or recorded window-ends are
maintained. The bare invocation always sweeps the last 14 days; the caller
chooses overlap consciously by picking the window.

**Repository resolution** (when not supplied explicitly):

```bash
gh repo view --json nameWithOwner --jq '.nameWithOwner'
```

If outside a git checkout and no repo is supplied, stop and ask.

## Phase 1 — Read-only gather

### 1.1 Bulk GraphQL gather (preferred)

Fetch merged/closed PRs in one or a few paginated GraphQL calls (~25 per
page). Include for each PR:

- `number`, `title`, `mergedAt`/`closedAt`, `state`, `author`, `mergeCommit`
- `commits(last:1)` → head commit SHA + `statusCheckRollup`
- `reviewThreads(first:100)` → `isResolved`, `isOutdated`, comments (author,
  body snippet)
- `reviews(first:20)` → author, state, submitted-at

Do **not** spawn one sub-agent per PR for initial data collection. Aggregate
locally; sub-agents are reserved for deep-reads in Phase 1.4.

Example skeleton (adapt fields as needed):

```graphql
query SweepPRs($owner: String!, $repo: String!, $after: String) {
  repository(owner: $owner, name: $repo) {
    pullRequests(
      states: [MERGED, CLOSED]
      orderBy: { field: UPDATED_AT, direction: DESC }
      first: 25
      after: $after
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title state mergedAt closedAt author { login }
        mergeCommit { oid }
        commits(last: 1) {
          nodes {
            commit {
              oid
              statusCheckRollup { state }
            }
          }
        }
        reviewThreads(first: 100) {
          nodes {
            isResolved isOutdated
            comments(first: 1) {
              nodes { author { login } body createdAt }
            }
          }
        }
        reviews(first: 20) {
          nodes { author { login } state submittedAt }
        }
      }
    }
  }
}
```

Paginate until `pageInfo.hasNextPage` is `false`, then filter client-side by
`mergedAt` / `closedAt` against the requested window. **Do not** stop the loop
early on the first out-of-window `mergedAt` / `closedAt` — the query orders by
`UPDATED_AT`, which is not correlated with merge/close time (a stale PR pushed
to the top by a recent comment can hide in-window PRs on later pages). If the
repository is large enough that full pagination is expensive, switch the query
to `orderBy: { field: CREATED_AT, direction: DESC }` and stop when `createdAt`
exits the window plus a safety buffer (long-running PRs created before the
window can still merge inside it).

### 1.2 Main-branch health (Check B)

Use server-side filters to avoid silent truncation:

```bash
gh api "repos/{owner}/{repo}/actions/runs?status=failure&per_page=50" \
  --jq '.workflow_runs[] | {id, name, conclusion, created_at, head_sha}'
```

Correlate failed runs on `main` against the PR merge timeline. **Do not**
client-side-filter `gh run list` — it silently truncates results before
applying filters.

### 1.3 Check categories

#### Check A — Merged without green builds

For each merged PR, inspect the `statusCheckRollup.state` on the merge-head
commit:

- `FAILURE` or `ERROR` → merged with failing checks
- `PENDING` → merged while checks still running
- `EXPECTED` (no checks configured) → flag for awareness, not necessarily a
  finding
- Has the failure been addressed post-merge? (look for a follow-up commit or
  fix-forward issue)

#### Check B — Merged while main was red

- Did the merge land while a `main` branch run was `failure`/`in_progress`?
- Did the merge fix the redness, ignore it, or worsen it?
- Was the redness tracked (existing issue / comment on the PR)?

#### Check C — Review thread hygiene

For each merged or closed PR with review threads:

- Unresolved threads at merge time (not `isResolved`, not `isOutdated`)
- Post-merge thread activity (reviewer commented after merge)
- Hollow resolutions (thread resolved by the PR author immediately after a
  request-changes review with no visible code change in between)
- Dangling threads on closed-not-merged PRs (unresolved threads on abandoned
  PRs that should be acknowledged or converted to issues)

#### Check D — Extensible case-by-case patterns

Review for:

- Admin-bypass merges (no required checks; infer from timeline anomalies or
  API `mergedBy` vs review state)
- PRs closed without comment (no disposition comment before close)
- Release-convention adherence (version bump PRs, changelog entries if the
  repo follows a convention)
- Any other patterns the caller instructs

### 1.4 Deep-reads via sub-agents (Phase 2 prep)

When a PR needs deeper inspection (e.g., large diff context, CI log
correlation), batch in groups of ~5 and delegate to sub-agents. Do not spawn
more than ~4 sub-agents concurrently for deep-reads.

## Phase 2 — Findings checkpoint

**Stop and present before making any mutation.**

Produce a findings table:

| PR | Title | Category | Evidence                           | Proposed Disposition                    |
|----|-------|----------|------------------------------------|-----------------------------------------|
| #N | ...   | A/B/C/D  | commit sha, check name, thread URL | open issue / resolve thread / no-action |

Categories: `A` merged-without-green, `B` main-was-red, `C` thread-hygiene,
`D` case-by-case.

Proposed dispositions:

- `open-issue` — create a fix-forward GitHub issue (via the `issue` skill)
- `resolve-thread` — post a disposition reply and resolve the review thread
- `reply-only` — post a note without resolving (e.g., closed-PR thread)
- `no-action` — rationale recorded; no change needed
- `needs-human` — judgment beyond skill scope; flag for owner

**Wait for explicit owner confirmation** before proceeding to Phase 3. If the
owner modifies or rejects proposed dispositions, update the table and reconfirm
before acting.

## Phase 3 — Remediate confirmed items

Execute only the confirmed dispositions from Phase 2.

### Fix-forward issues

For each `open-issue` disposition, follow the `issue` skill:

- Title: concise imperative (`Fix: <pr-title> merged with failing <check>`)
- Body: evidence (PR link, commit SHA, check name/URL), context, suggested
  resolution
- Labels: `bug` for failing-check merges; `tech-debt` for thread hygiene
- AI Implementation Prompt comment if the fix is automatable

### Thread dispositions

For `resolve-thread` items:

1. Post a brief reply on the thread explaining the disposition (fixed
   post-merge via issue #N, acknowledged as known gap, out of scope, etc.)
2. Resolve the thread via GraphQL (or `gh api`) if the platform supports
   agent resolution:

   ```bash
   gh api graphql -f query='
     mutation ResolveThread($id: ID!) {
       resolveReviewThread(input: {threadId: $id}) {
         thread { isResolved }
       }
     }
   ' -f id="<thread-node-id>"
   ```

3. For closed-PR threads (`reply-only`), post the note but do not attempt
   resolution (thread may already be locked).

### No-action rationales

For each `no-action` item, record the rationale in the final report. Do not
post on the PR unless the owner requests it (avoid noise on already-closed
PRs).

## Phase 4 — Final report

```text
## Sweep-PRs Report
Window: <start> → <end>  (e.g. 2026-06-19 → 2026-07-19)
Repository: owner/repo

### Summary
PRs audited: N
Findings: A=X, B=Y, C=Z, D=W
Actions taken: <issues opened>, <threads resolved>, <no-action recorded>

### Findings detail
<findings table from Phase 2, updated with actual outcome>

### Next sweep
Window end recorded above — choose overlap consciously when running next sweep.
No state is stored by this skill; bare `/sweep-prs` always starts from T-14d.
```

## Notes

- **Stateless**: this skill does not create tracking issues or store the window
  end. The report records the window-end timestamp so the operator can choose a
  conscious overlap on the next run.
- **Read-only Phase 1**: no mutations before the Phase 2 checkpoint. If an
  error occurs during gather, report partial findings and stop.
- **Scope**: audit only; does not revert merges or reopen PRs. Fix-forward is
  the remediation model.
- For per-PR shepherding of open PRs, use the `babysit-pr` skill. `sweep-prs`
  is the periodic fleet-wide complement — it handles already-merged/closed PRs
  across the full window, not live open ones.
