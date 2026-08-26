# lgtm-ci adoption audit

Inventory and adoption plan for [lgtm-hq/lgtm-ci](https://github.com/lgtm-hq/lgtm-ci)
reusable workflows, per issue
[#90](https://github.com/lgtm-hq/ai-skills/issues/90). Generated with
`scripts/audit_lgtm_ci_adoption.py` against the pinned ref
`23c79b65490a3307fb08cdefafa22db12f75b9b2` (v0.63.1).
`reusable-ai-review.yml` is pinned independently at
`62737ac1e3e0a25bd138d2d77d80ae03fb9741c5` (v0.67.0).

This document is inventory and plan. Adoptions land in focused follow-up
PRs (one workflow per PR).

## Summary

- Available reusable workflows at the pinned ref: **57**
- Adopted: **16**
- Deferred (with rationale): **2**
- Covered differently: **1**
- Not applicable: **38**

Regenerate the adopted/unadopted lists and counts with:

```bash
uv run python scripts/audit_lgtm_ci_adoption.py
```

The script exits non-zero on mixed pins, so re-running it after any repin
catches partial updates. All callers except ``reusable-ai-review.yml``
share `23c79b65490a3307fb08cdefafa22db12f75b9b2` (v0.63.1). Local
callers of ``reusable-ai-review.yml`` must share one SHA, include a
``tooling-ref``, and keep ``uses`` / ``tooling-ref`` in lockstep.

## Classification

| Reusable workflow | Status | Rationale |
| --- | --- | --- |
| `reusable-quality-lint.yml` | adopted | Called by `ci.yml`; runs lintro quality checks. Renamed upstream from `reusable-quality.yml` (which split into quality-lint + publish-quality-summary). |
| `reusable-publish-quality-summary.yml` | adopted | Called by `ci.yml`; posts the quality summary PR comment (the write-scoped half of the old `reusable-quality.yml`). |
| `reusable-validate.yml` | adopted | Called by `ci.yml`; runs `scripts/validate.sh`. |
| `reusable-test-python.yml` | adopted | Called by `ci.yml` ([#97](https://github.com/lgtm-hq/ai-skills/pull/97)); runs the pytest suite. |
| `reusable-validate-lintro-version.yml` | adopted | Called by `validate-lintro-version.yml`; fails the build if `pyproject.toml`'s `lintro==` pin drifts from the py-lintro image CI runs. Consumer repos pass `lintro-image` explicitly (see [lintro version alignment](#lintro-version-alignment)). |
| `reusable-pr-auto-assign.yml` | adopted | Called by `pr-auto-assign.yml` (added in [#77](https://github.com/lgtm-hq/ai-skills/pull/77)). |
| `reusable-release-auto-tag.yml` | adopted | Called by `release-auto-tag.yml`. |
| `reusable-release-version-pr.yml` | adopted | Called by `release-version-pr.yml`. |
| `reusable-scorecards.yml` | adopted | Called by `scorecards.yml`; OpenSSF Scorecard posture (#90 plan item 2). |
| `reusable-codeql.yml` | adopted | Called by `codeql.yml`; static analysis for the Python scripts in `scripts/` (#90 plan item 3). |
| `reusable-dependency-review.yml` | adopted | Called by `dependency-review.yml`; blocks vulnerable dependency changes on PRs (`pyproject.toml`/`uv.lock`) (#90 plan item 4). |
| `reusable-sbom.yml` | adopted | Called by `release-sbom.yml`; SBOM generation for releases (#90 plan item 5). |
| `reusable-link-check.yml` | adopted | Called by `link-check.yml`; checks Markdown links (offline internal on PRs, external weekly) (#90 plan item 6). |
| `reusable-pr-labeler.yml` | adopted | Called by `pr-labeler.yml`; applies labels from `.github/labeler.yml` on PR events (#90). No org-level fallback exists (see [org-level coverage](#org-level-coverage)); sibling repos adopt it per-repo. |
| `reusable-semantic-pr-title.yml` | adopted | Called by `semantic-pr-title.yml`; enforces Conventional Commits PR titles (#90). No org-level fallback exists (see [org-level coverage](#org-level-coverage)); sibling repos adopt it per-repo. |
| `reusable-required-check.yml` | deferred | Single required-status aggregation; most useful once branch protection exists — blocked on owner action ([#71](https://github.com/lgtm-hq/ai-skills/issues/71)). |
| `reusable-vuln-suppression-check.yml` | deferred | Keeps vulnerability suppressions reviewed and time-boxed; no suppression files exist in this repo yet — adopt when the first suppression appears. |
| `reusable-validate-action-pinning.yml` | covered-differently | SHA pinning is enforced by stand-ci convention and review today; automating it is a later hardening candidate. |
| `reusable-ai-review.yml` | adopted | Called by `ai-review.yml`; same-repo PRs get a `lintro-review[bot]` sticky review. Pins a newer lgtm-ci SHA than the shared quality/release pin because the current reusable contract landed after that pin. Pre-push `coderabbit` / `greptile` skills remain complementary. |
| `reusable-auto-rerun-on-infra-failure.yml` | not-applicable | Optional flake-recovery hardening; no observed infra-flake problem to warrant it — revisit if one appears. |
| `reusable-main-failure-notifier.yml` | not-applicable | No notification target wired; revisit if main-branch failure alerting is wanted. |
| `reusable-build-artifact.yml` | not-applicable | Nothing built or distributed; `scripts/` are repo-internal tooling. |
| `reusable-build-python-dist.yml` | not-applicable | Nothing built or distributed; `scripts/` are repo-internal tooling. |
| `reusable-build-rust-binaries.yml` | not-applicable | No Rust code. |
| `reusable-coverage.yml` | not-applicable | No coverage publishing target; revisit if the pytest job starts producing coverage artifacts. |
| `reusable-deploy-pages.yml` | not-applicable | No site/pages deployment. |
| `reusable-deploy-site-with-reports.yml` | not-applicable | No site/pages deployment. |
| `reusable-docker.yml` | not-applicable | No container images built or published. |
| `reusable-docker-build.yml` | not-applicable | No container images built or published. |
| `reusable-docker-multiplatform.yml` | not-applicable | No container images built or published. |
| `reusable-docker-smoke-test.yml` | not-applicable | No container images built or published. |
| `reusable-ghcr-cleanup.yml` | not-applicable | No GHCR packages to clean up. |
| `reusable-github-release.yml` | not-applicable | No build artifacts to attach; release tagging is handled by `reusable-release-auto-tag.yml`. |
| `reusable-prune-build-staging-tags.yml` | not-applicable | No build-staging tags produced (no Docker/build pipeline). |
| `reusable-publish-artifact-preview.yml` | not-applicable | No artifact-preview pipeline. |
| `reusable-publish-artifact-report.yml` | not-applicable | No artifact-report pipeline. |
| `reusable-publish-file-breakdown.yml` | not-applicable | No build-artifact file breakdown to publish. |
| `reusable-publish-gem.yml` | not-applicable | Nothing published to RubyGems. |
| `reusable-publish-npm.yml` | not-applicable | The npm gateway publishes via the repo's own `publish-npm.yml`; no lgtm-ci npm-publish surface is used. |
| `reusable-publish-rust-release.yml` | not-applicable | No Rust release surface. |
| `reusable-publish-security-audit-comment.yml` | not-applicable | No `reusable-security-audit.yml` pipeline to feed it. |
| `reusable-publish-test-summary.yml` | not-applicable | The pytest job runs with `publish-results` disabled; no test-summary PR-comment pipeline is wired. |
| `reusable-registry-health-check.yml` | not-applicable | No published registry packages to health-check. |
| `reusable-release-multi-ecosystem.yml` | not-applicable | Single-ecosystem release flow; no multi-ecosystem coordination needed. |
| `reusable-rust-build.yml` | not-applicable | No Rust code. |
| `reusable-rust-test.yml` | not-applicable | No Rust code. |
| `reusable-security-audit.yml` | not-applicable | Python-only repo; PR-time dependency-vulnerability blocking runs via `reusable-dependency-review.yml`. A scheduled audit can be revisited. |
| `reusable-site-quality.yml` | not-applicable | No site to quality-check. |
| `reusable-test-e2e.yml` | not-applicable | No e2e/browser surface. |
| `reusable-test-e2e-matrix.yml` | not-applicable | No e2e/browser surface. |
| `reusable-test-e2e-playwright.yml` | not-applicable | No e2e/browser surface. |
| `reusable-test-node.yml` | not-applicable | The npm gateway's `bun test` runs in its own package pipeline; no lgtm-ci Node test caller is wired. |
| `reusable-test-node-custom.yml` | not-applicable | No custom Node test surface wired to lgtm-ci. |
| `reusable-test-node-publish.yml` | not-applicable | No Node publish surface wired to lgtm-ci. |
| `reusable-test-python-publish.yml` | not-applicable | Nothing published to PyPI; `scripts/` are repo-internal tooling. |
| `reusable-test-rust-build.yml` | not-applicable | No Rust code. |
| `reusable-test-shell.yml` | not-applicable | Shell scripts are thin installers without a BATS suite; revisit if one is added. |

## lintro version alignment

`ci.yml`'s `quality` job runs lintro via `reusable-quality-lint.yml` with an
explicit `lintro-image` override (pinned by digest). To keep local
`uv run lintro chk` from drifting away from what CI enforces,
`pyproject.toml` exact-pins `lintro==0.81.1` and `uv.lock` resolves to the
same version. The override is required while this repo's lgtm-ci SHA still
defaults to an older image; bump the digest and the `lintro==` pin together
on every lintro upgrade — the guard fails loudly if they drift.

`reusable-validate-lintro-version.yml` guards this automatically: it runs
`lintro --version` inside the pinned image and fails if it disagrees with
the `lintro==` pin in `pyproject.toml`. As a consumer repo, ai-skills does
not vendor lgtm-ci's `reusable-quality-lint.yml` / `run-quality` action, so
`resolve-lintro-image.sh` cannot auto-discover the digest; both
`validate-lintro-version.yml` and `ci.yml` pass `lintro-image` explicitly.

## Org-level coverage

`reusable-pr-labeler.yml` and `reusable-semantic-pr-title.yml` have **no
org-level fallback**: `lgtm-hq/.github` contains only its own `ci.yml` (no
org-default workflows, no `workflow-templates/`). Sibling repos
(`py-lintro`, `winnow`, `Rustume`, `podex`) each adopt these per-repo with
SHA-pinned callers. This repo now adopts them per-repo as well:
`pr-labeler.yml` (config in `.github/labeler.yml`) and
`semantic-pr-title.yml`.

## Drift risks

- **lintro pin vs lock drift:** `pyproject.toml` exact-pins `lintro==0.81.1`
  to match the CI image override, and `reusable-validate-lintro-version.yml`
  (adopted via `validate-lintro-version.yml`) fails the build on any future
  drift. See [lintro version alignment](#lintro-version-alignment).
- **Single-SHA pin discipline:** quality/release callers share one SHA
  (`23c79b65490a3307fb08cdefafa22db12f75b9b2`, v0.63.1).
  `ai-review.yml` may pin a newer `reusable-ai-review.yml` SHA;
  `scripts/audit_lgtm_ci_adoption.py` excludes that name from repo-wide
  uniqueness. Local callers of `reusable-ai-review.yml` must still share
  one SHA and keep `uses` / `tooling-ref` in lockstep. Always pin to a SHA
  that is reachable from a tag or `main` — never to a PR-branch or
  squash-orphaned commit.
