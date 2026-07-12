# lgtm-ci adoption audit

Inventory and adoption plan for [lgtm-hq/lgtm-ci](https://github.com/lgtm-hq/lgtm-ci)
reusable workflows, per issue
[#90](https://github.com/lgtm-hq/ai-skills/issues/90). Generated with
`scripts/audit_lgtm_ci_adoption.py` against the pinned ref
`768a6b72f0a5346b5ecba3f4e13b90040472341c`.

This document is inventory and plan. Adoptions land in focused follow-up
PRs (one workflow per PR); several are in-flight — see
[In-flight adoptions](#in-flight-adoptions).

## Summary

- Available reusable workflows at the pinned ref: **45**
- Adopted: **8**
- Recommended for adoption: **7** (5 in-flight, 2 pending)
- Deferred (with rationale): **2**
- Covered differently: **1**
- Not applicable: **27**

Regenerate the adopted/unadopted lists and counts with:

```bash
uv run python scripts/audit_lgtm_ci_adoption.py
```

The script exits non-zero on mixed pins, so re-running it after any repin
catches partial updates. All eight callers share the single SHA above.

## Classification

| Reusable workflow | Status | Rationale |
| --- | --- | --- |
| `reusable-quality-lint.yml` | adopted | Called by `ci.yml`; runs lintro quality checks. Renamed upstream from `reusable-quality.yml` (which split into quality-lint + publish-quality-summary). |
| `reusable-publish-quality-summary.yml` | adopted | Called by `ci.yml`; posts the quality summary PR comment (the write-scoped half of the old `reusable-quality.yml`). |
| `reusable-validate.yml` | adopted | Called by `ci.yml`; runs `scripts/validate.sh`. |
| `reusable-test-python.yml` | adopted | Called by `ci.yml` ([#97](https://github.com/lgtm-hq/ai-skills/pull/97)); runs the pytest suite. Repinned to the shared SHA here (was on the pre-repin `fc73b3ab…`). |
| `reusable-validate-lintro-version.yml` | adopted | Called by `validate-lintro-version.yml`; fails the build if `pyproject.toml`'s `lintro==` pin drifts from the py-lintro image CI runs. Consumer repos pass `lintro-image` explicitly (see [lintro version alignment](#lintro-version-alignment)). |
| `reusable-pr-auto-assign.yml` | adopted | Called by `pr-auto-assign.yml` (added in [#77](https://github.com/lgtm-hq/ai-skills/pull/77)). |
| `reusable-release-auto-tag.yml` | adopted | Called by `release-auto-tag.yml`. |
| `reusable-release-version-pr.yml` | adopted | Called by `release-version-pr.yml`. |
| `reusable-scorecards.yml` | recommended | OpenSSF Scorecard posture; no supply-chain scoring runs today. In-flight (#90 plan item 2). |
| `reusable-codeql.yml` | recommended | Static analysis for the Python scripts in `scripts/`; none runs today. In-flight (#90 plan item 3). |
| `reusable-dependency-review.yml` | recommended | Blocks vulnerable dependency changes on PRs (`pyproject.toml`/`uv.lock`). In-flight (#90 plan item 4). |
| `reusable-sbom.yml` | recommended | SBOM generation for releases; complements the existing manifest attestation. In-flight (#90 plan item 5). |
| `reusable-link-check.yml` | recommended | Repo is mostly Markdown (skills, docs); links are unchecked today. In-flight (#90 plan item 6). |
| `reusable-pr-labeler.yml` | recommended | No org-level fallback exists (see [org-level coverage](#org-level-coverage)); sibling repos adopt it per-repo. Candidate for a per-repo caller; labeling currently comes from PR tooling/skills. |
| `reusable-semantic-pr-title.yml` | recommended | No org-level fallback exists (see [org-level coverage](#org-level-coverage)); sibling repos adopt it per-repo. Candidate for a per-repo caller; title convention is enforced today by the commit/pr skills and squash-merge policy. |
| `reusable-required-check.yml` | deferred | Single required-status aggregation; most useful once branch protection exists — blocked on owner action ([#71](https://github.com/lgtm-hq/ai-skills/issues/71)). |
| `reusable-vuln-suppression-check.yml` | deferred | Keeps vulnerability suppressions reviewed and time-boxed; no suppression files exist in this repo yet — adopt when the first suppression appears. |
| `reusable-validate-action-pinning.yml` | covered-differently | SHA pinning is enforced by stand-ci convention and review today; automating it is a later hardening candidate. |
| `reusable-build-python-dist.yml` | not-applicable | Nothing built or distributed; `scripts/` are repo-internal tooling. |
| `reusable-build-rust-binaries.yml` | not-applicable | No Rust code. |
| `reusable-coverage.yml` | not-applicable | No coverage publishing target; revisit if the pytest job starts producing coverage artifacts. |
| `reusable-deploy-pages.yml` | not-applicable | No site/pages deployment. |
| `reusable-deploy-site-with-reports.yml` | not-applicable | No site/pages deployment. |
| `reusable-docker.yml` | not-applicable | No container images built or published. |
| `reusable-ghcr-cleanup.yml` | not-applicable | No GHCR packages to clean up. |
| `reusable-github-release.yml` | not-applicable | No build artifacts to attach; release tagging is handled by `reusable-release-auto-tag.yml`. |
| `reusable-publish-artifact-report.yml` | not-applicable | No artifact-report pipeline. |
| `reusable-publish-gem.yml` | not-applicable | Nothing published to RubyGems. |
| `reusable-publish-npm.yml` | not-applicable | Nothing published to npm. |
| `reusable-publish-rust-release.yml` | not-applicable | No Rust release surface. |
| `reusable-publish-security-audit-comment.yml` | not-applicable | No `reusable-security-audit.yml` pipeline to feed it. |
| `reusable-publish-test-summary.yml` | not-applicable | The pytest job runs with `publish-results` disabled; no test-summary PR-comment pipeline is wired. |
| `reusable-registry-health-check.yml` | not-applicable | No published registry packages to health-check. |
| `reusable-rust-build.yml` | not-applicable | No Rust code. |
| `reusable-rust-test.yml` | not-applicable | No Rust code. |
| `reusable-security-audit.yml` | not-applicable | Python-only repo; PR-time dependency-vulnerability blocking is planned via `reusable-dependency-review.yml` (in-flight). A scheduled audit can be revisited. |
| `reusable-site-quality.yml` | not-applicable | No site to quality-check. |
| `reusable-test-e2e.yml` | not-applicable | No e2e/browser surface. |
| `reusable-test-e2e-matrix.yml` | not-applicable | No e2e/browser surface. |
| `reusable-test-node.yml` | not-applicable | No Node/TypeScript code. |
| `reusable-test-node-custom.yml` | not-applicable | No Node/TypeScript code. |
| `reusable-test-node-publish.yml` | not-applicable | No Node/TypeScript publish surface. |
| `reusable-test-python-publish.yml` | not-applicable | Nothing published to PyPI; `scripts/` are repo-internal tooling. |
| `reusable-test-rust-build.yml` | not-applicable | No Rust code. |
| `reusable-test-shell.yml` | not-applicable | Shell scripts are thin installers without a BATS suite; revisit if one is added. |

## In-flight adoptions

Plan items 2–6 of [#90](https://github.com/lgtm-hq/ai-skills/issues/90) —
`reusable-scorecards.yml`, `reusable-codeql.yml`,
`reusable-dependency-review.yml`, `reusable-sbom.yml`, and
`reusable-link-check.yml` — are being adopted in sibling PRs, one workflow
per PR. Those PRs intentionally do **not** edit this document, to avoid
merge conflicts across the parallel lanes; this table will be reconciled to
`adopted` as they land.

## lintro version alignment

`ci.yml`'s `quality` job runs lintro via `reusable-quality-lint.yml` with an
explicit `lintro-image` override
(`ghcr.io/lgtm-hq/py-lintro@sha256:ec90de3f…`, **0.74.0**). To keep local
`uv run lintro chk` from drifting away from what CI enforces,
`pyproject.toml` pins `lintro==0.74.0` (exact) and `uv.lock` resolves to
the same version. The override is required while this repo's lgtm-ci SHA
still defaults to an older image; bump the digest and the `lintro==` pin
together on every lintro upgrade — the guard fails loudly if they drift.

`reusable-validate-lintro-version.yml` guards this automatically: it runs
`lintro --version` inside the pinned image and fails if it disagrees with
the `lintro==` pin in `pyproject.toml`. As a consumer repo, ai-skills does
not vendor lgtm-ci's `reusable-quality-lint.yml` / `run-quality` action, so
`resolve-lintro-image.sh` cannot auto-discover the digest; both
`validate-lintro-version.yml` and `ci.yml` pass `lintro-image` explicitly.

## Org-level coverage

`reusable-pr-labeler.yml` and `reusable-semantic-pr-title.yml` are listed
as consumed in #90's Phase-1 comment, but no caller exists in this repo and
there is **no org-level fallback**: `lgtm-hq/.github` contains only its own
`ci.yml` (no org-default workflows, no `workflow-templates/`). Sibling repos
(`py-lintro`, `winnow`, `Rustume`, `podex`) each adopt these per-repo with
SHA-pinned callers. They are therefore genuinely unadopted here and are
per-repo adoption candidates rather than "covered elsewhere."

## Drift risks

- **lintro pin vs lock drift:** resolved — `pyproject.toml` exact-pins
  `lintro==0.74.0` to match the CI image override, and
  `reusable-validate-lintro-version.yml` (adopted via
  `validate-lintro-version.yml`) fails the build on any future drift. See
  [lintro version alignment](#lintro-version-alignment).
- **Single-SHA pin discipline:** all eight lgtm-ci callers share one SHA
  (`768a6b72f0a5346b5ecba3f4e13b90040472341c`);
  `scripts/audit_lgtm_ci_adoption.py` exits non-zero on mixed pins, so
  re-running it after any repin catches partial updates.
