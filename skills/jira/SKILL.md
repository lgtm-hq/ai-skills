---
name: jira
description: Generate Jira-style ticket descriptions. Use when the user says "/jira", "jira ticket", or "give me a Jira ticket".
disable-model-invocation: true
---

# Jira Ticket

Generate a structured Jira ticket description from context (conversation, code changes,
PR, or user description).

## Output Format

```text
**Title:** <imperative mood, concise>

**Type:** <Task | Bug | Story | Spike | Sub-task>

**Priority:** <Critical | High | Medium | Low>

**Component:** <infer from context, e.g. CI/CD, Auth, Tests, UI>

**Description:**

<1-2 sentences explaining the what and why>

**Acceptance Criteria:**
- <testable criterion>
- <testable criterion>
- ...

**PR:** <link if one exists>
```

## Rules

- Title: imperative mood, no Jira prefix (the user adds their own project key)
- Description: concise — explain the problem and the solution direction, not
  implementation details
- Acceptance criteria: specific, testable, checkboxable — not vague ("works correctly")
- Priority: infer from context (security = High/Critical, cosmetic = Low, functional =
  Medium)
- Component: infer from files touched or domain discussed
- PR link: include if a PR was created in the same conversation
- Omit optional fields (Epic, Sprint, Story Points) unless the user asks for them

## Examples

**Good acceptance criteria:**

- `pr-auto-assign.yml` assigns the PR author on `opened` events
- `bin/assign-random-codeowner.sh` is deleted
- CODEOWNERS review requests are unaffected

**Bad acceptance criteria:**

- It works
- The workflow is correct
- Tests pass
