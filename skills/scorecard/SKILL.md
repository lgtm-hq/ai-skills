---
name: scorecard
description: Audit the OpenSSF Scorecard rating for py-lintro. Use when asked to check the scorecard, understand the rating, or find what's missing. Specific to github.com/lgtm-hq/py-lintro.
---

# OpenSSF Scorecard Audit — py-lintro

Audit the OpenSSF Scorecard rating for `github.com/lgtm-hq/py-lintro` and identify what's dragging the score down.

## Step 1: Fetch Current Score

Run the following to get the latest scorecard results:

```bash
# Get the latest scorecard JSON from the API
curl -s "https://api.securityscorecards.dev/projects/github.com/lgtm-hq/py-lintro" | python3 -m json.tool
```

Also check the scorecard viewer: https://scorecard.dev/viewer/?uri=github.com/lgtm-hq/py-lintro

## Step 2: Evaluate Each Check

Compare the live results against the baseline findings below. For each check, determine whether the score has improved, regressed, or stayed the same.

### Baseline Findings (2026-02-20, score 5.8/10)

| Check | Score | Root Cause |
|---|---|---|
| **Code-Review** | 0/10 | Single maintainer — PRs by `TurboCoder13` have no distinct human reviewer. CodeRabbit (AI bot) reviews don't count. |
| **Token-Permissions** | 0/10 | Workflows escalate to `write` permissions at the job level (`packages: write`, `pull-requests: write`, `contents: write`). Scorecard wants minimal top-level permissions on every workflow file. |
| **Signed-Releases** | 0/10 | PyPI attestations and Docker provenance exist but scorecard expects Sigstore signatures or `actions/attest-build-provenance` on GitHub Release artifacts themselves. |
| **Pinned-Dependencies** | -1 (error) | `FROM ${TOOLS_IMAGE}` ARG indirection in Dockerfile causes a scorecard parsing error. The image IS pinned by digest — this is a known scorecard limitation. **Do not "fix" this** — the parameterization is load-bearing (used by CI, docker-compose, Makefile, scripts for PR testing with swappable tools images). Also: `apt-get install` on line 48 lacks version pins. |
| **Fuzzing** | 0/10 | No OSS-Fuzz or ClusterFuzzLite integration. |
| **CI-Tests** | 5/10 | Tests detected on only ~57% of merged PRs. Bot/release PRs (from `github-actions[bot]`) skip full test flow, skewing the metric. |
| **Security-Policy** | 4/10 | SECURITY.md uses a personal email instead of GitHub's private vulnerability reporting. |
| **Contributors** | 3/10 | Single human contributor. Inherent to the project — cannot easily change. |
| **CII-Best-Practices** | 2/10 | OpenSSF Best Practices badge was "InProgress". User reported 99% complete as of 2026-02-20 — scorecard may lag. |
| **Vulnerabilities** | 7/10 | Open Dependabot alerts (11 at baseline). |
| **SAST** | 8/10 | CodeQL configured but may not cover all commit paths. |
| **Branch-Protection** | 6/10 | Allstar configured but `requireStatusChecks` is empty and `requireCodeOwnerReviews` is false. |
| **Dependency-Update-Tool** | 10/10 | Renovate configured and active. |
| **Maintained** | 10/10 | Active development. |
| **Dangerous-Workflow** | 10/10 | No dangerous patterns. |
| **Binary-Artifacts** | 10/10 | Clean. |
| **Packaging** | 10/10 | OIDC trusted publishing to PyPI. |
| **License** | 10/10 | MIT. |

### Known Non-Issues (Do Not Recommend Fixing)

- **Pinned-Dependencies / Dockerfile ARG**: The `FROM ${TOOLS_IMAGE}` pattern is intentional and used across CI pipelines, docker-compose, Makefile, and scripts for build-time image swapping. The image is pinned by digest. Scorecard cannot parse ARG indirection — this is their bug, not ours.
- **Contributors**: Single-maintainer project. Score will naturally improve if more contributors join.
- **Code-Review**: Inherently limited by single-maintainer status. Would need a second trusted reviewer.

### GitHub Repo Settings to Check

```bash
# Check security settings
gh api repos/lgtm-hq/py-lintro --jq '.security_and_analysis'
```

At baseline, these were **disabled** (not scored by scorecard but still worth tracking):
- `secret_scanning`
- `secret_scanning_push_protection`
- `dependabot_security_updates`

## Step 3: Report

Present findings in this format:

```
## OpenSSF Scorecard Audit — py-lintro

**Current Score:** X.X/10
**Previous Score:** 5.8/10 (2026-02-20)
**Trend:** Improved / Regressed / Unchanged

### Check-by-Check Comparison

| Check | Baseline | Current | Delta | Notes |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

### What's Still Missing

1. [check] — [why it's still low and what would fix it]

### What Improved

1. [check] — [what changed]

### Recommended Next Actions (prioritized by score impact)

1. [action]
```

## Step 4: Update This Skill

If the audit reveals new findings, outdated information, or checks that have been resolved, update the baseline table in this skill file:

```
Edit /Users/eiteldagnin/.claude/skills/scorecard/SKILL.md
```

Update the following sections:
- **Baseline Findings** table — update scores, root causes, and the date
- **Known Non-Issues** — add or remove entries as appropriate
- **GitHub Repo Settings** — update if settings have changed

This keeps the skill accurate for future invocations.
