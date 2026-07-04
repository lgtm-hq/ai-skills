---
name: babysit-pr
description: >-
  Autonomously drive an open PR to merge-ready state by triaging Greptile and
  CodeRabbit review comments, fixing CI failures, handling CodeRabbit rate limits,
  and looping until checks are green with no unresolved actionable threads. Use when
  asked to babysit a PR, shepherd a PR, or keep a PR merge-ready until review/CI
  cycles complete.
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

## Hard rules

1. **Never approve or merge** the PR — only the human owner does that.
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

4. **Snapshot** before looping: PR URL, branch, worktree path, latest commit SHA,
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
   - Parse the wait time from the comment body.
   - **Sleep until after reset** — poll every 2–5 minutes; do not exit early.
   - After reset:
     - **If unpushed commits**: Step A → push → return to loop.
     - **If nothing to push**: post `@coderabbitai please review` on the PR, then wait
       for CodeRabbit to respond and triage any new threads (Step D).
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
  on the latest commit, with all threads triaged; not merely a stale green check or an
  outstanding rate-limit window without `@coderabbitai please review`.
- No unpushed local commits.
- Branch mergeable (no conflicts).

`REVIEW_REQUIRED` alone is **not** a loop blocker — note it in the final report.

## Phase 6 — Final report

Return a concise summary:

| Field | Value |
| --- | --- |
| PR | URL, title, number |
| Branch | name @ final SHA |
| CI | pass/fail per check |
| Commits pushed | list (short) |
| Threads handled | fixed / replied N/A |
| Merge-ready? | yes/no + why |
| Human blockers | approval, decisions, etc. |

## Notes

- Differs from the built-in Cursor `babysit` skill: this workflow is PR-parameterized,
  Greptile/CodeRabbit-aware, and enforces the lint gate and CodeRabbit rate-limit loop.
- Stacked branches on py-lintro sometimes need cherry-pick onto `main`, not a blind
  rebase — prefer conversation context or ask before rewriting history.
