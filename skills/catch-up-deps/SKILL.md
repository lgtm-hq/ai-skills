---
name: catch-up-deps
description: >-
  Org-wide dependency catch-up - fold every open and rate-limited Renovate
  update for a repo into one consolidated PR, migrate breaking majors, reassess
  vulnerability suppressions, shepherd it to merge and through release, then
  move to the next repo in the owner's priority order. Strict authority
  boundaries - no gate or toleration changes, no unrequested issues, bot-owned
  follow-ups merged from the bot's own PR. Use when asked to catch up
  dependencies, clear the Renovate backlog, or consolidate dependency PRs.
disable-model-invocation: true
---

# Catch Up Dependencies

Clear a repo's dependency backlog as **one consolidated PR per repo**, then
drive that PR to merged and released before starting the next repo. This may
run for hours across many repos. It composes `branch`, `commit`, `pr`,
`babysit-pr --merge` and `issue`; it adds the dependency-specific workflow and
the authority rules the owner set for it.

## Invocation

- `/catch-up-deps` — current repo only.
- `/catch-up-deps lgtm-hq/a lgtm-hq/b lgtm-hq/c` — explicit repos, **in
  priority order**. Finish one before starting the next.
- `/catch-up-deps ... --hold lgtm-hq/x lgtm-hq/y` — repos the owner has parked.
  Never touch them, even for a one-line bump.

Invoked outside any repo with no repo argument: ask which repos, don't guess.

## Hard rules

1. **One PR per repo.** Everything folds into it: every open Renovate PR
   **and** every update parked in the Dependency Dashboard's rate-limited or
   pending sections. No ticking dashboard checkboxes, no second PR, no
   unrelated fixes riding along. The only extra changes allowed are the
   migrations a breaking bump forces.
2. **Authority boundaries apply** — read the `stand-general` skill's
   **Authority boundaries** section first. In this workflow they bite as:
   - never add, remove or relax a CI gate, skip allowlist, toleration or lint
     suppression, in either direction, even when an entry looks stale;
   - never file an issue to record your own finding or proposal; say it in
     one sentence and let the owner decide;
   - when a bot will open the follow-up (image digest bump, release version
     PR, tap bump), merge **the bot's PR**; close stale bot PRs with a pointer
     to the superseding one instead of merging old ones;
   - publish gates and environments are human gates unless the owner granted
     approval, and then one in flight per environment.
3. **Breaking majors are migrated, never dodged** (`stand-general`,
   Dependency Update Triage). Closing a hard bump to make the PR green is a
   violation.
4. **Vulnerability suppressions are reassessed, not carried.** Remove ignores
   whose advisory is fixed by the bump. For advisories still unpatched add a
   time-boxed ignore with a reachability reason, an expiry, and a link to the
   issue or upstream fix that removes it. These are the only suppression edits
   this workflow may make.
5. **Red `main` is P0.** If `main` is or goes red during the work: stop the
   lane, fix through the normal branch → PR → babysit path, following the
   repo's standing policy on whether that fix gets its own issue. Never
   re-green a gate by configuring around it.
6. **Green means all of it.** Merge only with every check green and every
   review thread resolved by a fix or a reasoned reply (`babysit-pr`).
7. **Cheaper models implement, you orchestrate and review.** Hand mechanical
   lockfile and version work to a lower-cost sub-agent where the harness
   supports it; keep migrations, suppression decisions and merges yourself.

## Phase 0 — Scope and readiness

1. Record the repo order and the hold list. Confirm both back to the owner in
   one line before touching anything.
2. For each repo, from its checkout root, read `AGENTS.md` and/or `CLAUDE.md`
   (precedence per `stand-general`). Repo-specific facts that matter here:
   toolchain for lockfile regeneration, release rules, merge policy, and any
   agent identity wrapper that must front git and GitHub writes.
3. If another session is working the same org, agree ownership per repo and
   per shared file before starting. Never touch worktrees or branches that
   are not yours.
4. Signing and identity pre-flight: confirm commits sign and the identity
   wrapper (when the repo names one) reports ready. A locked key or a failed
   wrapper is surfaced now, not discovered mid-run. Never fall back to
   personal credentials when the wrapper fails.

## Phase 1 — Inventory (read-only, per repo)

Gather before writing anything:

- **Open bot PRs**: `gh pr list --author app/renovate --state open --json
number,title,headRefName,files`, plus Dependabot if present.
- **Rate-limited and pending updates**: read the Dependency Dashboard issue
  body. Each unchecked line is an update that has no PR yet; it still goes
  into the consolidated PR. Do not tick the boxes.
- **Suppression files**: every vulnerability ignore the repo carries (for
  example `.osv-scanner.toml`, `.cargo/audit.toml`, `deny.toml`,
  `.trivyignore`, pip-audit or npm audit config). Note each advisory id and
  what it currently excuses.
- **Release rules**: which commit types cut a release (often only `feat` and
  `fix`), whether the repo is 1 PR = 1 release, and which publish gates are
  human-approved.
- **Coupled pins**: anything that must move together with a bump but is
  produced after merge (tool-version minimums and the Docker digest they are
  verified against, generated manifests, baked indexes). Record how the repo
  closes that loop so you can predict the post-merge window.

Decide the squash title type now. If the repo's release rules would not
release on `chore(deps)` but the catch-up changes what consumers install, ask
the owner which type to use. Do not retype a bot title on your own.

## Phase 2 — Build the consolidated branch

1. Create the tracking issue per the `issue` skill, one per repo, listing every
   folded update with its Renovate PR number or dashboard line. The owner asked
   for this issue; it is part of the workflow, not a finding.
2. `branch -w` a worktree named `chore/<issue>-dependency-catch-up` from a
   **freshly fetched `origin/main`**.
3. Apply each update, smallest blast radius first: actions and image digests,
   then dev tooling, then runtime libraries, then majors. Cherry-pick a
   Renovate branch when it applies cleanly; otherwise edit the manifest and
   regenerate the lockfile with the repo's own toolchain (`uv lock`,
   `bun install`, `cargo update -p`, ...). Never hand-edit a lockfile.
4. Migrate every breaking major in the same branch. Read the upstream
   changelog; fix the code, config and tests that the bump breaks.
5. Reassess suppressions per Hard rule 4. Where a scanner database lags the
   advisory (an ignore for an id the tool has never seen fails as "not
   encountered"), leave that file alone and document why in the ignore you
   did add.
6. Run the **full** lint and **full** test suite before every commit (`lint`,
   `test`). Validate the paths CI does not cover: a green lockfile bump can
   still break an un-CI'd Docker stage or an optional extra.
7. Commit per the `commit` skill. Routine bumps can be one commit; each
   migration gets its own so review can follow it.

## Phase 3 — Open and shepherd

1. Open the PR per the `pr` skill with `Closes #<tracking issue>`. The body
   lists every folded update, the Renovate PR it supersedes, each migration,
   and each suppression change with its reason and expiry.
2. If the AI reviewer refuses the diff for size and the bulk is lockfiles,
   the fix is a review-config exclusion for lockfiles, landed **first** as its
   own small PR. Propose it to the owner; do not merge the catch-up unreviewed.
3. Run `babysit-pr --merge` on the consolidated PR. Judge review threads on
   their merits; `CANCELLED` legs from superseded runs are not failures, but
   an all-checks gate that still counts them needs a fresh head, not a rerun.
4. After merge, Renovate closes most of its own PRs once `main` carries the
   versions. Close any that remain with a comment pointing at the merged PR
   (`issue` skill, Backlog Stewardship). Never close them before the merge.

## Phase 4 — Release and post-merge

1. Watch every run on the merge commit until it settles. A red `main` here is
   Hard rule 5.
2. If a version PR appears, merge it per the repo's release convention and
   wait for its runs. If none appears because the squash type does not
   release, report that; do not force a release through a retyped empty PR.
3. Publish gates: leave them to the owner unless approval was granted. With
   a grant, approve one environment at a time, wait for that step to finish,
   and only then approve the next. One PyPI and one npm in flight at most,
   across all releases.
4. Coupled pins (Phase 1): wait for the bot to open the digest or manifest
   bump against the new `main`, then merge that bot PR. Close older digest
   PRs it supersedes with a pointer. Hand-rolling the same change is a
   violation of Hard rule 2 even when it would land faster.
5. Verify the release reached every channel the repo publishes to (package
   index, npm, GitHub release, tap or marketplace) before calling the repo
   done. Then start the next repo.

## Waiting well

- Watch runs with a single watcher per thing watched; verify instance count
  before re-arming, and stop a watcher before replacing it.
- Before cancelling or re-running a run that looks stalled, confirm with the
  jobs API that it has no running job. A gate waiting on an upstream job is
  not a stall.
- Platform incidents (startup failures, empty matrices, missing jobs) are not
  code failures. Wait for the status page, then re-trigger once.

## Reporting

- One line per repo: merged PR, release version, channels confirmed, anything
  still open. Keep it short.
- Separate **what is waiting on the owner** from what is merely in progress.
- When a stale pattern shows up (a bump that always reddens `main`, a release
  rule that skips `chore(deps)`), describe it in one or two sentences and ask
  whether to file it. Do not file it.

## Failure signatures

- **Version minimum bumped, image digest not yet promoted** → `main` red on
  the image-manifest verify until the bot's digest PR lands. Expected window;
  merge the bot PR, never add a toleration.
- **`chore(deps)` squash cut no release** → repo release rules exclude it.
  Ask the owner how to type consolidated dependency PRs in that repo.
- **Review refused for size on a lockfile-heavy diff** → lockfiles belong in
  the review exclusion list; land that first (Phase 3, step 2).
- **New vulnerability ignore fails as "advisory not encountered"** → the
  scanner's database lacks the id; do not mirror the ignore into that tool.
- **All-checks gate red from a cancelled leg of an older run** → fresh head
  SHA (rebase or empty commit), not a rerun of the old run.

## Notes

- Origin: 2026-11-09 org-wide catch-up across lgtm-hq (py-lintro, lgtm-ci,
  turbo-themes, ai-skills, Rustume). The authority rules here are the ones
  the owner enforced during that run; see lgtm-hq/ai-skills#666 for the
  consolidated-PR shape.
- Complement to `babysit-pr` (which shepherds any PR) and `backlog` (which
  routes issue and PR work). This skill owns the dependency-specific
  inventory, consolidation, suppression and release-chain steps.
