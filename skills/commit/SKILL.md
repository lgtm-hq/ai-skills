---
name: commit
description: Pre-commit workflow and commit guidelines. Use when asked to commit changes. Requires passing lint and tests, signed commits, semantic prefixes, imperative mood.
---

# Commit

Pre-commit workflow and commit guidelines.

## Pre-commit Checklist

Before making ANY commit:

1. Run the `/lint` workflow — all checks must pass with zero issues (abort if any
   issues remain). See `/lint` — full check, no `--tools` filtering.
2. All tests must pass (`uv run lintro tst`)
3. Where applicable, Docker builds pass

## Commit Requirements

- Every commit MUST be signed/verified
- Use semantic commit prefixes: `fix:`, `feat:`, `chore:`, `docs:`, `refactor:`,
  `test:`, `build:`, `ci:`, `perf:`, `style:`
- Commit messages MUST be in imperative mood ("Add feature" not "Added feature")

## Commit Granularity

Make incremental, logical commits rather than one large commit:

- Group related changes (e.g., all logging for one subsystem)
- Separate concerns (e.g., bug fixes vs features vs docs)
- Each commit should be independently reviewable and revertable
- Use judgment: 1 commit per file is too granular, 1 commit for everything is too coarse

Good groupings:

- `feat(logging): add subprocess execution logging` (one component)
- `feat(logging): add config parsing logging` (related files)
- `docs: add debugging guide` (documentation separate from code)

Bad groupings:

- One commit with 11 files touching 4 different concerns
- 11 separate commits for a cohesive feature

## Branch Context Awareness

When working on a new extension or feature branch where all files are new:

- Every file should show as "A" (added), never "M" (modified)
- If you see "M" on files that should be new, the commit history needs fixing
- This indicates commits were made in the wrong order or need restructuring

When modifying an existing codebase:

- "M" (modified) is expected and correct
- Focus on logical grouping of related changes

## Restructuring Commits

If commits are poorly structured (too large, wrong groupings, or showing modified when
should be added):

1. Find the commit before the problematic ones: `git log --oneline`
2. Soft reset to that point: `git reset --soft <good-commit>`
3. Unstage all changes: `git reset HEAD`
4. Re-add and commit in logical groups with proper messages
5. Verify with `git status` that file statuses (A/M) are correct

## Usage

When asked to commit:

1. Run the `/lint` workflow — abort if any issues remain (see `/lint` — full check,
   no `--tools` filtering)
   - Raycast extensions: run `uv run lintro fmt/chk` first, then `npm run lint` per
     the `raycast` skill (Raycast rules take precedence)
   - Other projects without lintro: use the appropriate lint command from `/lint`
2. Run tests - abort if any failures:
   - Projects with lintro: `uv run lintro tst`
   - Raycast extensions: `ray test`
   - Other projects: use appropriate test command
   - When authoring or modifying a Raycast extension, use the `raycast` skill for
     toolchain-specific guidance
3. Check Docker if applicable
4. Review changes with `git status` to plan logical groupings
5. Stage and commit in logical groups with signed, semantic, imperative messages:

   ```bash
   git add <related-files>
   git commit -S -m "feat: add user authentication"
   ```

6. Repeat steps 4-5 for each logical group of changes

## Examples

Good commit messages:

- `fix: resolve null pointer in user service`
- `feat: add dark mode toggle`
- `chore: update dependencies`
- `docs: improve API documentation`
- `refactor: simplify authentication flow`

Bad commit messages:

- `fixed bug` (not semantic, past tense)
- `WIP` (not descriptive)
- `updates` (not semantic, not specific)
