---
name: issue
description: Create GitHub issues with proper formatting, labels, and AI implementation prompts. Use when asked to create an issue, report a bug, or request a feature.
---

# GitHub Issue Creation

Create well-structured GitHub issues following repository conventions.

## Issue Title Format

Use semantic prefixes matching conventional commits:

```text
feat(scope): short description    # New feature
fix(scope): short description     # Bug fix
docs(scope): short description    # Documentation
chore(scope): short description   # Maintenance
refactor(scope): short description # Code refactoring
perf(scope): short description    # Performance improvement
```

## Issue Body Structure

### For Feature Requests

```markdown
## Summary

One paragraph describing the feature and its value.

## Problem

What problem does this solve? What's the current limitation?

## Proposed Solution

Detailed description with:

- Code examples showing desired behavior
- ASCII diagrams or mockups if applicable
- Configuration examples

## Implementation Notes

- Key files to modify
- Dependencies or prerequisites
- Potential challenges

## Benefits

- Bullet points of user/developer benefits
```

### For Bug Reports

```markdown
## Summary

One paragraph describing the bug.

## Problem

What's happening vs what should happen?
Include:

- Steps to reproduce
- Error messages or screenshots
- Environment details if relevant

## Proposed Solution

How to fix it (if known).

## References

- Links to related issues, docs, or resources
```

## Labels

Apply appropriate labels based on issue type:

| Issue Type        | Labels                    |
| ----------------- | ------------------------- |
| New feature       | `enhancement`             |
| Bug fix           | `bug`                     |
| Documentation     | `documentation`           |
| Security issue    | `bug`, `security`         |
| CI/CD related     | `ci`                      |
| New tool (lintro) | `enhancement`, `new tool` |

## AI Implementation Prompt

For issues that involve code changes, add a comment with an AI implementation prompt:

````markdown
## AI Implementation Prompt

Use this prompt in a new agent session to implement this feature:

\```
[Concise implementation instructions including:]

## Requirements

### 1. [First Component]

- What to create/modify
- Code examples

### 2. [Second Component]

- What to create/modify
- Code examples

## Files to Modify

- `/path/to/file.py` - description of changes

## Tests

- Test requirements (pytest style, NO test classes)
- Use assertpy, fixtures

## Before Submitting

- Run `uv run lintro chk` - must pass
- Run `uv run lintro fmt` - must pass
- Run `uv run pytest` - must pass
  \```
````

## Usage

When asked to create an issue:

1. **Gather requirements** - Ask clarifying questions if needed
2. **Review existing issues** - Check for duplicates with `gh issue list`
3. **Create the issue**:

   ```bash
   gh issue create \
     --title "feat(scope): description" \
     --label "enhancement" \
     --body "$(cat <<'EOF'
   ## Summary
   ...
   EOF
   )"
   ```

4. **Add AI prompt comment** (for implementation issues):

   ```bash
   gh issue comment <issue-number> --body "$(cat <<'EOF'
   ## AI Implementation Prompt
   ...
   EOF
   )"
   ```

5. **Return the issue URL** to the user

## Backlog Stewardship

Rules for managing an existing backlog, not just creating new issues.

- **Comment before closing.** Every closed issue gets a comment explaining
  *why* it's closed and linking to whatever supersedes it (issue, PR, or
  commit).
  - Don't: `gh issue close 42` with no comment.
  - Do: `gh issue comment 42 --body "Superseded by #57, merged in a1b2c3d."`
    then `gh issue close 42`.
- **"Done" means merged to `main`.** Work that exists only on a branch is not
  done. Never close an issue because a branch has the fix — reopen or
  repurpose the issue instead until it lands on `main`.
- **Repurpose before minting.** When scope evolves, prefer retargeting an
  existing issue number over closing it and opening a new one — it preserves
  history and discussion.
- **Placeholder convention for duplicates.** For issues that are redundant or
  would only duplicate another: prefer closing with a supersession comment
  (see above) when the issue has useful comments, an implementation prompt,
  **or a useful body** (repro steps, scoped feature spec, acceptance criteria)
  — do not wipe history that other links or workflows may still need. Only
  convert to a `placeholder` (empty body, title `placeholder`, comments
  cleared) when the issue has **no useful body and no useful discussion** to
  preserve and you are explicitly reserving the number for reuse.
- **Never churn the backlog silently.** Announce close/reopen/create/edit
  changes as you make them — the backlog should stay visible, not shift
  underneath readers.
- **Keep content correct.** Issues must carry accurate scope and follow the
  `/issue` format above. When an assessment (audit, review, incident)
  surfaces a real gap — bug, security issue, tech debt — add a spec-formatted,
  labeled issue for it rather than leaving it undocumented.
- **Dependency-update issues/PRs** (Renovate, Dependabot): follow the
  dependency-triage rule in the `stand-general` skill.

## Examples

### Good Issue Titles

- `feat(cli): add watch mode for continuous linting`
- `fix(parser): handle empty input without crashing`
- `docs(readme): add installation instructions for Windows`
- `refactor(core): simplify plugin loading logic`

### Bad Issue Titles

- `Add feature` (no scope, not descriptive)
- `Bug` (not descriptive)
- `Update code` (vague, no scope)
- `Fixed the thing` (past tense, vague)
