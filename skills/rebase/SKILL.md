---
name: rebase
description: Rebase the current branch onto the latest main. Use when asked to rebase, sync with main, update branch, or pull latest changes. Fetches, rebases, and force-pushes with lease.
---

# Rebase

Rebase the current branch onto the latest `origin/main`.

## Usage

When asked to rebase:

1. **Check current state**:
   ```bash
   git status
   git branch --show-current
   ```
   - If on `main`, warn the user and stop — rebasing main onto itself is a no-op
   - If there are uncommitted changes, warn the user and stop — do NOT stash automatically

2. **Fetch latest**:
   ```bash
   git fetch origin
   ```

3. **Rebase onto main**:
   ```bash
   git rebase origin/main
   ```

4. **Handle conflicts**:
   - If the rebase succeeds cleanly, proceed to step 5
   - If there are conflicts:
     - List the conflicting files
     - Ask the user how they want to proceed: resolve manually, or abort
     - Do NOT force-continue or blindly resolve conflicts
     - To abort: `git rebase --abort`

5. **Confirm** — Print a summary:
   ```
   Rebased feat/123-add-watch-mode onto origin/main
   ```
   - Do NOT push automatically
   - If the user explicitly asks to push, use `git push --force-with-lease`
   - NEVER use `--force` — always `--force-with-lease` for safety

## Important

- NEVER rebase `main` itself
- NEVER use `git push --force` — always `--force-with-lease`
- NEVER stash or discard uncommitted changes — warn and stop
- NEVER use `--no-edit` or `-i` flags with rebase
- If conflicts occur, always involve the user — never auto-resolve
