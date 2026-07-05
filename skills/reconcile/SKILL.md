---
name: reconcile
description: Consolidate worktrees and clean up stale branches. Use when asked to reconcile, clean up worktrees, consolidate branches, or tidy up a project's git state.
---

# Reconcile

Consolidate worktrees into the main worktree and clean up stale branches for a project.

## Arguments

Accepts an optional project name as an argument:

- `/reconcile` — reconcile the current working directory's project
- `/reconcile py-lintro` — reconcile the project at `~/Code/py-lintro`

## Workflow

### Phase 1 — Discovery

1. **Identify the project root**:
   - If a project name is given, look for `~/Code/<project-name>`
   - Otherwise, use the current git repository root
   - Confirm it's a git repository — if not, stop

2. **Find all worktrees**:

   ```bash
   git worktree list
   ```

3. **Find sibling directories** that may be related:
   - List directories matching `<project-name>-*` in the same parent directory
   - For each, check if it's:
     - A **worktree** (`.git` is a file pointing to the main repo)
     - A **separate clone** (`.git` is a directory with same remote)
     - **Unrelated** (different remote or not a git repo) — ignore these

4. **Collect all branches**:

   ```bash
   git branch -vv --no-color
   ```

### Phase 2 — Analysis

For each branch (excluding `main`/`master`), determine its status:

1. **Check remote tracking**:
   - If tracking branch shows `gone` → remote branch was deleted (PR likely merged or
     closed)
   - If tracking branch exists → check PR status

2. **Check GitHub PR status** (if `gh` is available):

   ```bash
   gh pr list --state all --json number,title,headRefName,state
   ```

   - Map each branch to its PR (if any)
   - Categorize: `merged`, `open`, `closed` (without merge), or `no PR`

3. **Check for uncommitted changes** in each worktree:

   ```bash
   git -C <worktree-path> status --short
   ```

4. **Check for stashes**:

   ```bash
   git stash list
   ```

5. **Check if main worktree is on `main`** — flag if it's on a feature branch

### Phase 3 — Report

Present a summary to the user, grouped by action:

```text
Project: turbo-themes
Main worktree: ~/Code/turbo-themes (on refactor/265 — should be main)

Worktrees to remove:
  ✅ turbo-themes-267-...  → fix/267-text-contrast (PR #350 merged, clean)
  ✅ turbo-themes-build-.. → fix/build-ci-site     (PR #359 merged, clean)
  ⚠️  turbo-themes-ci-...   → fix/ci-missing-rose   (PR #356 merged, 3 uncommitted files)

Branches to delete (PRs merged):
  fix/267-text-contrast-state-buttons-light-themes
  fix/build-ci-site-missing-core-dep
  fix/ci-missing-rose-pine-synced

Branches to keep:
  📌 feat/landing-page-redesign — no PR, unmerged work

Separate clones found:
  🔶 ~/Code/turbo-themes-test — separate clone, not a worktree

Stashes: 5 (all on merged branches)
```

### Phase 4 — Confirm

Ask the user to confirm the plan (use a structured question tool if available):

- Which branches to keep vs delete
- Whether to remove separate clones
- Whether to clear stale stashes
- Confirm that uncommitted changes will be stashed

Do NOT proceed without explicit confirmation.

### Phase 5 — Execute

After confirmation, perform the cleanup in this order:

1. **Remove worktree directories**:
   - Try `git worktree remove <path>` first
   - Before any fallback delete, resolve `<path>` to a canonical path and verify all of
     the following:
     - Path is non-empty and exists
     - Path is NOT `/` and NOT the home directory
     - Path is under an allowed prefix (repo sibling worktree/clone root)
     - Path is not a symlink escaping the allowed prefix
   - Only with explicit user confirmation, if removal still fails (orphaned directory),
     run `rm -rf <path>` then `git worktree prune`

2. **Stash uncommitted changes** (if any, on branches being kept):

   ```bash
   git -C <worktree-path> stash push -m "reconcile: WIP on <branch-name>"
   ```

3. **Switch main worktree to the default branch**:

   ```bash
   DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD | sed 's#^origin/##')
   git checkout "$DEFAULT_BRANCH"
   git pull
   ```

4. **Delete merged branches**:

   ```bash
   git branch -d <branch1> <branch2> ...
   ```

5. **Clear stale stashes** (only if user confirmed):
   - Drop stashes that reference deleted branches

6. **Remove separate clones** (only if user confirmed):

   ```bash
   rm -rf <clone-path>
   ```

   - Apply the same canonical path-safety checks before deletion (non-empty, exists, not
     `/` or home, within allowed prefix, no symlink escape)

### Phase 6 — Verify

Print the final state:

```text
=== worktrees ===
~/Code/turbo-themes  abc1234 [main]

=== branches ===
  feat/landing-page-redesign  def5678  unmerged work
* main                        abc1234  [origin/main] latest commit message

=== stashes ===
(none)
```

## Important

- NEVER delete branches or worktrees without asking the user first
- ALWAYS stash uncommitted changes before cleanup
- NEVER force-push or modify remote state
- NEVER delete `main` or `master` branches
- Always present the full picture before taking action
- If a directory can't be identified as a worktree or clone, flag it and ask — don't
  assume
- If `gh` is not available, fall back to checking remote tracking status only
- Branches with open PRs should default to "keep" in the recommendation
- Branches with no PR and no remote should be flagged for user decision
