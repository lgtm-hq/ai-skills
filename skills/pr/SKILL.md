---
name: pr
description: Create pull requests with proper templates and metadata. Use when asked to create a PR, open a pull request, or submit changes for review. Auto-assign and auto-labeling handled by CI.
---

# Pull Request

Create pull requests with proper templates and metadata.

## Requirements

- PR should use the PR template of the current repository
- Assignee is automatically set by CI (random CODEOWNER)
- Labels are automatically applied by CI based on changed files

## Issue Detection

If the branch name contains an issue number (e.g., `feat/123-add-feature`,
`fix/45-parser-crash`), extract it and fetch the issue details:

```bash
gh issue view <number> --json title,body,labels
```

Use the issue context to:
1. Link the issue using the **Closes** section format (see below)
2. Inform the PR summary and description from the issue's title and body

If no issue number is found in the branch name, skip this step.

## Issue Link Format

**Always** use this exact format when linking issues in a PR body. Replace the
repo's `## Related Issues` template section with a `## Closes` section:

```markdown
## Closes

- Closes #123
- Closes #456
- Relates to #789
```

This format ensures GitHub renders rich issue links (with title, status, etc.)
automatically. Do **not** append the issue title after the number — GitHub
handles that via its rich formatting.

Rules:
- Use a `## Closes` heading (not `## Related Issues`)
- Each link is a bullet point: `- Closes #<number>`
- Use `Relates to` instead of `Closes` for issues that are related but not
  fully resolved by this PR
- Do **not** add any text after the issue number (no titles, no descriptions)

## Usage

When asked to create a PR:

1. **Ensure pre-commit checks pass** (lint, test, Docker if applicable)
2. **Push the branch to remote**
3. **Detect associated issue** from branch name (see above)
4. **Read the repo's PR template**: look for `.github/PULL_REQUEST_TEMPLATE.md`
5. **Fill in the PR template** with actual content:
   - **Summary**: Concise description of what the PR does and why
   - **Type**: Check the matching type checkbox (feat, fix, test, etc.)
   - **Changes Made**: Bullet list of specific changes
   - **Closes**: Replace `## Related Issues` with `## Closes` section
     using the issue link format specified above
   - **Testing**: Check boxes for tests that were added/run
   - **Quality Checks**: Check boxes for lint/format/build that passed
   - **Checklist**: Check all applicable items
   - Leave sections like Breaking Changes, Screenshots, Deployment Notes
     with their placeholder comments if not applicable
6. **Create the PR**:
   ```bash
   gh pr create --title "<title>" --body "<filled template>"
   ```
   Use a HEREDOC for the body to preserve formatting.

**Important**: Do NOT use `gh pr create --fill` — it only uses the commit
message and skips the PR template entirely. Always read and fill the template.

Note: Assignees and labels are handled automatically by GitHub Actions:
- `pr-auto-assign.yml` - Assigns a random CODEOWNER
- `pr-labeler.yml` - Labels based on changed files (see `.github/labeler.yml`)

## Checklist

Before creating PR:
- [ ] All linting passes
- [ ] All tests pass
- [ ] Branch is pushed to remote
- [ ] Associated issue detected and linked (if branch has issue number)
- [ ] PR template read and filled with actual content
- [ ] PR created with filled template (not `--fill`)
