# lgtm-ci adoption audit

Inventory and adoption plan for [lgtm-hq/lgtm-ci](https://github.com/lgtm-hq/lgtm-ci)
reusable workflows, per issue
[#90](https://github.com/lgtm-hq/ai-skills/issues/90). Generated with
`scripts/audit_lgtm_ci_adoption.py` against the pinned ref
`fc73b3ab8342a24597c12d137d6ff7fca84b9fe2`.

This document is inventory and plan only — adoption lands in follow-up
PRs (one workflow per PR).

## Summary

- Available reusable workflows at the pinned ref: **27**
- Adopted: **5**
- Recommended for adoption: **6** (plus 2 post-repin candidates)
- Covered differently: **3**
- Not applicable: **13**

Regenerate with:

```bash
uv run python scripts/audit_lgtm_ci_adoption.py
```

## Classification

| Reusable workflow | Status | Rationale |
| --- | --- | --- |
| `reusable-quality.yml` | adopted | Called by `ci.yml`; runs lintro quality checks. |
| `reusable-validate.yml` | adopted | Called by `ci.yml`; runs `scripts/validate.sh`. |
| `reusable-pr-auto-assign.yml` | adopted | Called by `pr-auto-assign.yml` (added in #77). |
| `reusable-release-auto-tag.yml` | adopted | Called by `release-auto-tag.yml`. |
| `reusable-release-version-pr.yml` | adopted | Called by `release-version-pr.yml`. |
| `reusable-scorecards.yml` | recommended | OpenSSF Scorecard posture; no supply-chain scoring runs today. |
| `reusable-codeql.yml` | recommended | Static analysis for the Python scripts in `scripts/`; none runs today. |
| `reusable-dependency-review.yml` | recommended | Blocks vulnerable dependency changes on PRs (`pyproject.toml`/`uv.lock`). |
| `reusable-sbom.yml` | recommended | SBOM generation for releases; complements the existing manifest attestation. |
| `reusable-link-check.yml` | recommended | Repo is mostly Markdown (skills, docs); links are unchecked today. |
| `reusable-test-python.yml` | recommended | Audit finding: the pytest suite in `tests/` runs only locally — CI never executes it. |
| `reusable-pr-labeler.yml` | covered-differently | #90 lists it as consumed, but no caller exists at this pin; labeling currently comes from PR tooling/skills. Verify or adopt during the repin. |
| `reusable-semantic-pr-title.yml` | covered-differently | #90 lists it as consumed, but no caller exists at this pin; title convention enforced by the commit/pr skills and squash-merge policy. Verify or adopt during the repin. |
| `reusable-validate-action-pinning.yml` | covered-differently | SHA pinning is enforced by stand-ci convention and review today; automating it is a later hardening candidate. |
| `reusable-coverage.yml` | not-applicable | No coverage publishing target; revisit if `reusable-test-python.yml` adoption produces coverage artifacts. |
| `reusable-deploy-pages.yml` | not-applicable | No site/pages deployment. |
| `reusable-docker.yml` | not-applicable | No container images built or published. |
| `reusable-ghcr-cleanup.yml` | not-applicable | No GHCR packages to clean up. |
| `reusable-publish-gem.yml` | not-applicable | Nothing published to RubyGems. |
| `reusable-publish-homebrew.yml` | not-applicable | No Homebrew formula. |
| `reusable-publish-npm.yml` | not-applicable | Nothing published to npm. |
| `reusable-publish-pypi.yml` | not-applicable | Nothing published to PyPI; scripts are repo-internal tooling. |
| `reusable-test-e2e.yml` | not-applicable | No e2e/browser surface. |
| `reusable-test-e2e-matrix.yml` | not-applicable | No e2e/browser surface. |
| `reusable-test-node.yml` | not-applicable | No Node/TypeScript code. |
| `reusable-test-pr-comment.yml` | not-applicable | No test-summary PR-comment pipeline to feed it. |
| `reusable-test-shell.yml` | not-applicable | Shell scripts are thin installers without a BATS suite; revisit if one is added. |

### Post-repin candidates (not present at the pinned ref)

These exist in current lgtm-ci but not at
`fc73b3ab…`; adopting them rides the pending repin (the lgtm-ci release
containing lgtm-ci#378, same repin as #37).

| Reusable workflow | Status | Rationale |
| --- | --- | --- |
| `reusable-required-check.yml` | recommended | Single required-status aggregation instead of enumerating branch-protection checks. |
| `reusable-vuln-suppression-check.yml` | recommended | Keeps vulnerability suppressions reviewed and time-boxed. |

## Drift risks

- **lintro pin vs lock version drift:** CI's `reusable-quality.yml` runs
  a pinned `py-lintro` image (see `lintro-image` in lgtm-ci) that is
  older/laxer than this repo's local lock (`lintro>=0.62.1` in
  `pyproject.toml`, resolved in `uv.lock`). Issue #90 noted 2 mypy
  findings passing CI but failing locally; at the current lock this
  audit observes 5 (all `untyped-decorator` on the repo's
  `pytest.mark.parametrize` uses in `tests/`). Fix pin/lock alignment
  (and these findings) as part of the repin
  (lgtm-ci offers `reusable-validate-lintro-version.yml` at newer refs
  to guard exactly this).
- **Single-SHA pin discipline:** all lgtm-ci callers currently share one
  SHA; `scripts/audit_lgtm_ci_adoption.py` exits non-zero on mixed pins,
  so re-running it after any repin catches partial updates.
