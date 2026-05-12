---
name: branch
description: >-
  Start work on a new branch or worktree. Use when asked to start a new branch,
  new worktree, begin work on a feature/fix, or start fresh. Supports issue numbers
  and plain descriptions.
---

# Branch

Start work on a new git branch, optionally in a new worktree.

## Arguments

Accepts one of the following as arguments:

- **Issue number**: e.g., `/branch 123` — fetches the issue title and derives the
  branch name
- **Description**: e.g., `/branch add shellcheck support` — derives the branch name
  from the text
- **Worktree flag**: append `--worktree` or `-w` to create a git worktree instead of
  a regular branch

Examples:

- `/branch 123` — branch from issue #123
- `/branch add dark mode toggle` — branch from description
- `/branch 123 --worktree` — worktree from issue #123
- `/branch fix login redirect -w` — worktree from description

## Branch Naming

Derive the branch name using this format:

```text
<type>/<issue-number?>-<slug>
```

- **type**: Infer from context — `feat/`, `fix/`, `chore/`, `docs/`, `refactor/`,
  `perf/`, `test/`, `ci/`
  - If an issue has labels like `bug` → `fix/`, `enhancement` → `feat/`,
    `documentation` → `docs/`
  - If a description starts with a semantic prefix, use it
  - Default to `feat/` if unclear
- **issue-number**: Include only if an issue number was provided
- **slug**: Lowercase, hyphenated, max ~50 chars, derived from the issue title or
  description
  - Strip filler words when too long
  - e.g., "Add shellcheck support for shell scripts" → `add-shellcheck-support`

Examples:

- Issue #123 titled "feat(cli): add watch mode" → `feat/123-add-watch-mode`
- Issue #45 labeled `bug`, titled "Parser crashes on empty input" →
  `fix/45-parser-crashes-on-empty-input`
- Description "add dark mode" → `feat/add-dark-mode`
- Description "fix: resolve null pointer" → `fix/resolve-null-pointer`

## Usage — Regular Branch

When asked to start a new branch (no `--worktree` / `-w` flag):

1. **Ensure clean state**:
   - Run `git status` — if there are uncommitted changes, warn the user and stop
   - Do NOT stash or discard changes automatically
2. **Fetch latest**:

   ```bash
   git fetch origin
   ```

3. **Resolve branch name**:
   - If an issue number was given, fetch it:
     `gh issue view <number> --json title,labels`
   - Derive the branch name per the naming rules above
4. **Create and switch to the branch**:

   ```bash
   git checkout -b <branch-name> origin/main
   ```

5. **Confirm** — Print the branch name and a summary of what was done

## Usage — Worktree

When `--worktree` or `-w` is specified:

1. **Ensure clean state**:
   - Run `git status` — if there are uncommitted changes, warn the user and stop
2. **Fetch latest**:

   ```bash
   git fetch origin
   ```

3. **Resolve branch name** (same rules as above)
4. **Determine worktree path**:
   - Place as a **sibling directory** to the current repo
   - Format: `<repo-dir>-<slug>` (without the type prefix)
   - e.g., if repo is at `~/Code/py-lintro` and branch is `feat/123-add-watch-mode`:
     - Worktree path: `~/Code/py-lintro-123-add-watch-mode`
   - e.g., if branch is `fix/parser-crash`:
     - Worktree path: `~/Code/py-lintro-parser-crash`
5. **Create the worktree**:

   ```bash
   git worktree add -b <branch-name> <worktree-path> origin/main
   ```

6. **Confirm** — Print the worktree path, branch name, and how to navigate there:

   ```text
   Created worktree at ~/Code/py-lintro-123-add-watch-mode
   Branch: feat/123-add-watch-mode (from origin/main)

   To start working:
     cd ~/Code/py-lintro-123-add-watch-mode
   ```

## Important

- NEVER force-delete branches or worktrees
- NEVER stash or discard uncommitted changes — always warn and stop
- Always branch from `origin/main` (freshly fetched)
- If the branch name already exists, warn the user and ask what to do
