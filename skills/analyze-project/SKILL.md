---
name: analyze-project
description: High-level project analysis. Use when asked to analyze, review, or evaluate a project's architecture, structure, and overall health.
---

# Project Analysis (Zoom Out)

Perform a high-level analysis of this project. Follow the procedural workflow below;
use the rubric sections as reference when interpreting findings.

## Ground rules

- Reproduce before reporting — read the actual files and run the tooling; never assert
  a finding based on file names, directory shapes, or vibes alone.
- Verify catalog-like claims mechanically — if a claim implies "all N of X", script the
  check rather than eyeballing a sample.
- Mark anything you couldn't verify as "unverified"; never guess or extrapolate.
- This is an assessment only: no code changes, no pushes, no triggering workflows or
  releases.
- Honor the target repo's standing context file when present (see step 0).

## Usage

When asked to analyze project health:

### 0. Load repo context

At start, read the target repo's `AGENTS.md` and/or `CLAUDE.md` if present.
**Precedence:** `AGENTS.md` is authoritative when both exist — do not also
apply conflicting `CLAUDE.md` instructions; if only one exists, use that
file; if both conflict in a blocking way, stop and ask. Treat house
standards, operating agreement, and standing constraints in the chosen file
as **binding** for this assessment — including safety limits such as no paid
LLM API calls or local-only storage. See the `stand-general` skill's
**Per-repo agent context** section for the expected file shape. If neither
file exists, continue with chat instructions and `stand-*` skills only.

### 1. Map structure

Understand layout and entry points:

```bash
find . -maxdepth 3 -type f \( -name '*.py' -o -name '*.ts' -o -name '*.rs' -o -name 'Cargo.toml' -o -name 'package.json' -o -name 'pyproject.toml' \) | head -80
tree -L 3 -I 'node_modules|target|.venv|dist|build|__pycache__|.git' 2>/dev/null || find . -maxdepth 3 -type d | head -60
```

Note: source roots, module boundaries, config locations, and test directories.

### 2. Check CI/CD

Inspect automation and pipeline coverage:

```bash
ls -la .github/workflows/ 2>/dev/null
rg -l 'lint|test|build|deploy' .github/workflows/
rg -n --hidden "uses:.*@[0-9a-f]{40}\b" .github/workflows || echo "No SHA-pinned actions found"
```

Verify lint, test, and deploy stages exist; check for pinned action SHAs and reproducible
builds. Then go beyond presence: is CI validating what actually matters, or just
linting? Look for conditional skips (`if: ... == ''`, path filters that silently
no-op a job) and for test suites that exist in the repo but never run in any
workflow — CI claiming a check happens is not the same as it executing.

### 3. Dependency health

Confirm lock files and manifest consistency:

```bash
ls -1 *lock* uv.lock bun.lockb Cargo.lock package-lock.json poetry.lock Pipfile.lock 2>/dev/null
rg -n 'version|dependencies' pyproject.toml package.json Cargo.toml | head -30
```

Flag missing lock files, unpinned versions, or stale dependency patterns.

### 4. README and docs check

Assess onboarding and API documentation:

```bash
test -f README.md && head -80 README.md
find . -maxdepth 2 \( -name '*.md' -o -name 'docs' -type d \) | head -20
rg -l 'TODO|FIXME|TBD' README.md docs/
```

Check for setup instructions, contribution guide, and documented public APIs.

### 5. Hardcoded config search

Find scattered or environment-specific values in source:

```bash
rg -n '(localhost|127\.0\.0\.1|0\.0\.0\.0|hardcoded|FIXME.*config)' --glob '!*.{lock,sum,md}'
rg -n '(API_URL|BASE_URL|DATABASE_URL)\s*=\s*["\x27]' --glob '!*.example' --glob '!*.env*'
```

Evaluate against externalized configuration expectations.

### 6. Coupling and circular dependencies

Assess module boundaries (adapt to language):

```bash
# Python import graph (rough)
rg -n '^from |^import ' --type py | head -50

# TypeScript/JavaScript cross-imports
rg -n "^import .* from ['\"]\.\./" -t ts -t js | head -50

# Rust crate modules
rg -n '^mod |^pub mod ' -t rust | head -30
```

Look for deep cross-package imports, god modules, and circular import chains.

### 7. Backlog, PR state, and release discipline

Check the project against its own tracking, not just its code:

```bash
gh pr list --state open
gh issue list --state open
gh pr list --state merged --limit 20
```

If `gh` is unavailable or unauthenticated, mark these GitHub-backed checks as
"unverified" per the ground rules and continue the assessment.

Check for: stale or conflicting open PRs; issues claimed as done that are not actually
done in the code (verify by reading the code, not by trusting labels or comments);
merge history vs. stated milestones; lockfile version vs. manifest version drift;
CHANGELOG entries vs. `git log`; git tags vs. published releases.

### 8. Dead surface

Find things that look wired up but aren't — verify by reference, not by name:

- Workflows that silently skip themselves (conditional gates on paths/branches that
  never match)
- Scripts in the repo that no workflow, README, or Makefile ever calls
- Modules or components with zero references (`rg` for imports/usages of the symbol,
  not just its existence)
- Stale committed artifacts (build output, generated files checked in as source)
- Orphaned docs/content unreachable from any nav, index, or README link

### 9. Product-quality scorecard

Build one row per area of the codebase — the full catalog, not a sample. Columns:

| Area | Correctness risk (low/med/high) | Test coverage (y/partial/none) | Consistency (ok/drifts) | Staleness / dead-code flags | Action |
| ---- | -------------------------------- | ------------------------------- | ------------------------ | ---------------------------- | ------ |

Sort worst-first. Follow with the distribution across risk levels, the top 5-10
highest-risk areas, and any repo-wide patterns the scorecard reveals.

### 10. Rate and report findings

For each issue, assign severity:

- **Critical** — no CI, no lock files in production apps, secrets in repo, broken build
- **Should Fix** — poor docs, hardcoded config, unclear boundaries, missing tests in CI
- **Nice to Have** — naming inconsistencies, missing ADRs, UX polish

Output contract: lead with a TLDR verdict, then findings with `file:line` references,
then the scorecard and its summary, and end with **one** prioritized fix list ordered
by impact — not one list per section.

### Full audit

For a complete audit rather than a zoom-out-only pass, follow this skill with
analyze-code and analyze-tests, then merge all three sets of findings into the single
prioritized fix list described above.

---

## Reference — Architecture & Design

- Overall design quality and alignment with stated objectives
- Adherence to SOLID principles and separation of concerns
- Are layers (transport, business logic, data) clearly separated?
- API/interface design—are contracts clean, consistent, and hard to misuse?
- Code complexity—is it appropriately simple or over-engineered?
- Whether it reinvents solutions that existing libraries handle well

## Reference — Maintainability

- How easily could a new developer onboard and contribute?
- Is the code self-documenting, or are complex sections unexplained?
- Consistent naming conventions and project structure
- Boundary clarity—are public vs internal APIs clearly delineated?
- Change impact—how localized is the blast radius of a typical change?
- Configuration management—is config externalized properly vs scattered/hardcoded?

## Reference — CI/CD & DevOps

- Is the build reproducible?
- Are lint, test, and deploy pipelines in place?
- Are dependencies pinned and lock files committed?

## Reference — Documentation

- README quality—does it cover setup, usage, and contribution?
- API documentation—are public interfaces documented?
- Architecture decision records (ADRs) or equivalent for key decisions

## Reference — User Experience

- Interface design and usability
- Consistency of behavior and feedback
- Accessibility considerations

## Reference — Retrospective

If starting this project today, what would you do differently?
