---
name: babysit-pr
description: >-
  Autonomously drive an open PR to merge-ready state by triaging Greptile and
  CodeRabbit review comments, fixing CI failures, handling CodeRabbit rate limits,
  and looping until checks are green with no unresolved actionable threads. With
  the --merge flag, also merge the PR(s) once binding merge-queue conditions are
  met. Use when asked to babysit a PR, shepherd a PR, or keep a PR merge-ready
  until review/CI cycles complete.
disable-model-invocation: true
---

# Babysit PR

Drive an open pull request to a merge-ready state. This may run for hours — work
autonomously in a loop until done or blocked.

## Invocation

Examples:

- `/babysit-pr on #1034`
- `Babysit PR #1034 until merge-ready`
- `Babysit this PR` (resolve from current branch)
- `/babysit-pr --merge #124 #125 #126` (shepherd **and** merge, in queue order)

One babysitter for many PRs beats one babysitter per PR — they share a single
CodeRabbit rate limit, so a single session drains the queue without multiplying
review-limit stalls.

## Hard rules

1. **Never approve** the PR. **Never merge unless invoked with `--merge`** — the flag
   is the explicit authorization to merge; without it, only the human owner merges.
2. **Lint before every commit** — read and follow the `lint` skill (`uv run lintro fmt`
   then `uv run lintro chk`, zero issues). Do not use `--tools` filtering.
3. **Never push while CI is pending or running** on the PR head.
4. **Minimal diffs** — fix only what the PR scope and valid review/CI feedback require.
5. **Never weaken CI/workflows** just to make checks pass; report instead if that seems
   necessary.
6. **Never force-push**, amend pushed commits, or rewrite history unless the user
   explicitly requested it.

## Composed skills

- **`lint`** — pre-commit formatting and checks (required gate).
- **`commit`** — conventional commits, signed commits, semantic prefixes.
- **`gh-fix-ci`** (if available) — inspect failing GitHub Actions checks and logs.

Do not duplicate their full workflows here — read and follow them at commit time.

## Phase 0 — Resolve target PR

1. **PR number**: Extract from the user message (`#123`, URL) or resolve from the
   current branch:

   ```bash
   gh pr view --json number,url,title,headRefName,baseRefName,state,mergeable,mergeStateStatus
   ```

2. **Repository**: Use `gh repo view --json nameWithOwner` from the worktree, or parse
   from a PR URL.

3. **Worktree**: Prefer a path from conversation context. Otherwise scan worktrees:

   ```bash
   git worktree list
   ```

   Match `headRefName` to a worktree path. If none exists, use the current git root
   only when it matches the resolved PR branch. Otherwise stop and ask for the
   correct worktree before continuing.

4. **Load repo context** (after the target worktree is known): From that worktree
   root only, read `AGENTS.md` and/or `CLAUDE.md` if present. **Do not** read
   context from the parent checkout or any other repo. **Precedence:**
   `AGENTS.md` is authoritative when both exist — do not also apply conflicting
   `CLAUDE.md` instructions; if only one exists, use that file; if both conflict
   in a blocking way, stop and ask. Treat house standards, operating agreement
   (including merge policy / merge-queue notes), and standing constraints as
   **binding** for this babysit run. See the `stand-general` skill's **Per-repo
   agent context** section for the expected file shape. Missing the file is fine
   — fall back to chat instructions and this skill's defaults.

5. **Snapshot** before looping: PR URL, branch, worktree path, latest commit SHA,
   check summary, open review threads.

## Phase 1 — Launch background sub-agent (if supported)

Babysitting is long-running. After Phase 0, if the agent supports background sub-agents
(e.g. Claude Code's general-purpose agent run in the background), launch one and pass it
the resolved PR metadata, worktree path, hard rules, and this skill's main loop (Phase 2
onward). In that mode, the parent agent returns immediately with the sub-agent link and
handoff snapshot. The sub-agent runs until exit conditions are met or a human blocker is
found.

**Portability note:** on agents without background sub-agents, skip the handoff,
tell the user the babysitting loop will occupy the current session, and run the
main loop (Phase 2 onward) inline instead.

## Phase 2 — Main loop

Repeat until exit conditions (Phase 5) or a blocker. Track loop iterations and elapsed
time; **stop and report** if more than 20 iterations or 6 hours pass without reaching
exit conditions (avoids unbounded token/API cost on flaky CI or re-triggering bots).

### Step A — Wait for CI

```bash
gh pr checks <number> --repo <owner/repo>
```

If any check is `pending` or `in_progress`, wait and re-poll. **Re-poll every 60
seconds; after five consecutive pending polls, double the interval up to 5 minutes.**
**Do not push** during this window.

### Step B — Merge conflicts

If `mergeable` is `CONFLICTING`, resolve intelligently in the worktree preserving branch
intent. If intents conflict, stop and report — do not guess.

If the branch is behind base and failures look unrelated, merge onto latest base per
repo convention. Only rebase/cherry-pick if the user explicitly approves rewriting
history.

### Step C — Fix CI failures

For each failing GitHub Actions check:

1. Get check status via `gh pr checks --json`; fetch logs separately with
   `gh run view <run_id> --log`.
2. Fix failures **within PR scope** in the worktree.
3. Run project tests if applicable (follow the `test` skill or repo convention).
4. Lint gate → commit (follow `commit` skill) → push.
5. Return to Step A.

For external CI providers (non-GitHub Actions), report the details URL only.

### Step D — Triage review comments

Fetch unresolved review threads and recent bot comments:

```bash
gh api graphql -f query='...'  # or gh pr view --comments, issue comment APIs
```

**Sources**: Greptile, CodeRabbit (`coderabbitai[bot]`), Bugbot, human reviewers.

For each actionable thread:

1. Read the comment and the cited code location.
2. **Verify against current code** — skip or reply N/A if outdated or already fixed.
3. **Fix valid issues** with minimal diffs; lint → commit → push (after Step A allows).
4. **Reply briefly** on invalid/outdated findings (one short paragraph, no argument).
5. Resolve the thread when the platform supports it and the issue is addressed.

**Greptile**: Often posts a summary comment plus inline findings — treat inline items
like review threads.

**Bugbot**: Validate carefully; only fix real bugs. Explain when disagreeing.

**CodeRabbit**: See Step E for rate limits; otherwise triage like other bots.

When reading GitHub API output, fetch only comment bodies and locations needed — do not
load entire JSON payloads into context.

### Step E — CodeRabbit review cycle (mandatory)

CodeRabbit is not done when its GitHub check says "Review completed" on an **older**
commit. The babysit loop must cover the **current PR head**.

1. Record the latest commit SHA (`gh pr view --json headRefOid`).
2. Find the latest CodeRabbit issue comment:

   ```bash
   gh api repos/<owner>/<repo>/issues/<number>/comments \
     --jq '.[] | select(.user.login | test("coderabbit"; "i")) | {id, created_at, body}'
   ```

3. **Rate-limited** (`Review limit reached` / `Next review available in`):
   - **Do not sleep or poll for the reset** — the rate limit does not block exit.
   - **If unpushed commits exist**: push per Step A discipline (CI quiescent first),
     then return to the loop.
   - Record that CodeRabbit review of the **current head** is pending due to the rate
     limit, and continue toward the Phase 5 exit conditions.
4. **Not rate-limited but head unreviewed** (latest CodeRabbit summary/walkthrough
   comment is **older** than the current head commit, or only a rate-limit comment
   exists): post `@coderabbitai please review`, then wait and triage.
5. Do not burn CodeRabbit CLI runs during babysit — PR bot comments are the source of
   truth.
6. Repeat Step E after every push until CodeRabbit has reviewed the current head and
   all resulting threads are triaged.

### Step F — Re-check and repeat

After push, return to Step A. Continue until Phase 5 exit conditions.

## Phase 3 — Push discipline

Before every push:

1. CI quiescent (Step A).
2. Lint gate passed.
3. Commit signed and conventional.
4. CodeRabbit rate limit respected (Step E).

```bash
git push origin HEAD
```

## Phase 4 — Human blockers (stop and report)

Stop the loop and report if:

- Merge conflicts you cannot resolve safely.
- CI failures outside PR scope or requiring workflow changes.
- Missing credentials / permissions.
- Ambiguous product or design decisions.

Do not approve the PR to unblock it.

Do **not** stop solely because `REVIEW_REQUIRED` or branch protection needs human
approval — that is expected. When all other Phase 5 exit conditions are met, exit
successfully and note pending approval in the final report.

## Phase 5 — Exit conditions

Done when **all** are true:

- All required CI checks green (or only allowed skips like `REVIEW_REQUIRED`).
- No unresolved actionable Greptile/CodeRabbit/Bugbot threads (fixed or replied).
- **CodeRabbit has reviewed the current head** — summary/walkthrough or inline review
  on the latest commit, with all threads triaged — **or** CodeRabbit is rate-limited
  and the pending review of the current head is noted in the final report.
- No unpushed local commits.
- Branch mergeable (no conflicts).

`REVIEW_REQUIRED` alone is **not** a loop blocker — note it in the final report.

## Merging (only with `--merge`)

Skip this entire section unless invoked with `--merge`. Without the flag, exit at
Phase 5 and let the human owner merge.

### Capability check (first)

Before the first merge, detect what the repository provides:

- **Merge queue / auto-merge enabled?** — `gh repo view --json autoMergeAllowed`,
  ruleset inspection (`gh api repos/<owner>/<repo>/rulesets`), or a note in the repo's
  `CLAUDE.md`.
- **Conversation resolution required?** — branch protection / ruleset settings.

If the repo has a merge queue or auto-merge, use **queue-aware mode**. Otherwise fall
back to **manual serial mode**. The per-PR gate, release handling, failure signatures,
and signing-park behavior below apply to **both** modes.

### Per-PR gate (both modes)

Before merging (or enqueuing) any single PR:

- **Phase 5 exit conditions met** for that PR.
- **Bot reviewed the CURRENT head** — if the head moved since the last CodeRabbit
  review, re-request (`@coderabbitai please review`) and wait before merging — **or**
  CodeRabbit is rate-limited and the pending review of the current head is noted in the
  final report.
- **Re-check PR state immediately before merge** — an already-merged PR is a normal
  outcome, not an error; re-baseline the queue and move on.

### Queue-aware mode (primary, when available)

Per PR: resolve all review threads (fix or refute — Step D unchanged), get checks
green, then enqueue and observe:

```bash
gh pr merge <n> --auto --squash --delete-branch
```

**Never pass `--subject` or `--body` to `gh pr merge`** (either mode). Repo squash
defaults produce the correct commit on their own: PR title + auto-appended `(#N)` +
blank body. An explicit `--subject` suppresses the `(#N)` append (seen: py-lintro
`#1916`/`#1922` landed numberless); a custom `--body` trips commitlint
`body-max-line-length` on main's dogfood. "Squash with PR title and blank body"
means *rely on the defaults*, not *pass them as flags*.

The platform serializes merges, rebases each PR, merges when its turn comes, and
blocks on unresolved threads. Do **not** re-implement that machinery: no manual
main-green waiting between merges, no single-merger lock, no hand-rolled ordering.
Thread resolution is the irreducible judgment step and stays with the babysitter;
the mechanical serialization belongs to the platform. Keep observing until each
enqueued PR actually merges (or is ejected from the queue — then triage why).

**Never use `--admin` in this mode** — it uses administrator privileges against the
**whole** merge requirement set (reviews, required checks, queue enrollment,
blocked/behind state), so it bypasses queue enrollment entirely or masks a genuine
failure. If the merge fails **solely** because of the self-approval restriction, that
is a human blocker: stop and report it (see Phase 4) so the human owner reviews and
merges — do not reach for `--admin` to push past branch protection.

### Manual serial mode (fallback — no merge queue / auto-merge)

Merge command:

```bash
gh pr merge <n> --squash --admin --delete-branch
```

Guardrails for `--admin` here: use it **only** when the owner has explicitly granted
merge authority for the listed PRs (the `--merge` invocation naming them); the admin
bypass clears the review requirement **only** — all required checks must be genuinely
green (never skipped or forced). `--admin` stays forbidden in queue-aware mode, where
it would bypass queue enrollment.

Queue discipline (this mode only):

- **Single merger** — before starting, verify no other session is draining the same
  queue. One merger at a time.
- **Strictly sequential** — after each merge, wait for **all** post-merge runs on
  `main` to finish before merging the next PR.
- **A `main` run fails post-merge → STOP and report.** No fix-forward; the queue halts
  until a human decides.
- **Order by conflict** — merge docs/config-only PRs first, wide-touch refactors last,
  to minimize rebases.
- Under strict up-to-date-branch policies, use `gh pr update-branch <n>` to bring each
  PR current before its turn.

### Releases (both modes)

- Expect **auto version PRs** to appear after merges.
- If the repo convention is **1 PR = 1 release**, merge the release PR and wait for its
  runs before moving to the next change PR.
- **Never touch publish gates** (PyPI environment approval, etc.) — those are human
  gates. Stop and report.

### Failure signatures (both modes)

- **`CANCELLED`** = a duplicate/superseded run; only `FAILURE` / `TIMED_OUT` are
  genuine failures.
- **Stale merge ref** (setup fails on infra added to `main` after the PR was created)
  → `gh pr update-branch`; reruns of the old ref fail deterministically.
- **Pages "Multiple artifacts named github-pages"** → delete the run's `github-pages`
  artifacts via the API, then rerun; partial reruns re-hit this forever.
- **Registry "manifest unknown" on partial reruns** (a cleanup job deleted the
  run-scoped tags) → rerun the **entire** run, not just the failed job.
- **Signing locked ("failed to write commit object")** → park with ~20-minute probes,
  resume on unlock, and report the blocker once (not on every probe).

## Phase 6 — Final report

Return a concise summary:

| Field | Value |
| --- | --- |
| PR | URL, title, number |
| Branch | name @ final SHA |
| CI | pass/fail per check |
| Commits pushed | list (short) |
| Threads handled | fixed / replied N/A |
| CodeRabbit | reviewed current head / review pending (rate-limited) |
| Merge-ready? | yes/no + why |
| PRs merged | list (or n/a without `--merge`) |
| Human blockers | approval, decisions, etc. |

## Notes

- Differs from the built-in Cursor `babysit` skill: this workflow is PR-parameterized,
  Greptile/CodeRabbit-aware, and enforces the lint gate and CodeRabbit rate-limit loop.
- Stacked branches on py-lintro sometimes need cherry-pick onto `main`, not a blind
  rebase — prefer conversation context or ask before rewriting history.
- See also `backlog`: the interactive routing entry point that composes this
  skill with `implement-issues`. It does not auto-invoke either.
- See also `sweep-prs`: the periodic, fleet-wide complement — where this skill
  watches the PR it's actively merging, `sweep-prs` retrospectively audits
  everything else across repos.
