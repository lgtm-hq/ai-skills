---
name: analyze-project
description: High-level project analysis. Use when asked to analyze, review, or evaluate a project's architecture, structure, and overall health.
---

# Project Analysis (Zoom Out)

Perform a high-level analysis of this project. Follow the procedural workflow below;
use the rubric sections as reference when interpreting findings.

## Usage

When asked to analyze project health:

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
rg -l 'lint|test|build|deploy' .github/workflows/ 2>/dev/null
```

Verify lint, test, and deploy stages exist; check for pinned action SHAs and reproducible
builds.

### 3. Dependency health

Confirm lock files and manifest consistency:

```bash
ls -1 *lock* uv.lock bun.lockb Cargo.lock package-lock.json poetry.lock Pipfile.lock 2>/dev/null
rg -n 'version|dependencies' pyproject.toml package.json Cargo.toml 2>/dev/null | head -30
```

Flag missing lock files, unpinned versions, or stale dependency patterns.

### 4. README and docs check

Assess onboarding and API documentation:

```bash
test -f README.md && head -80 README.md
find . -maxdepth 2 \( -name '*.md' -o -name 'docs' -type d \) | head -20
rg -l 'TODO|FIXME|TBD' README.md docs/ 2>/dev/null
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
rg -n "^import .* from ['\"]\.\./" --type ts --type tsx --type js 2>/dev/null | head -50

# Rust crate modules
rg -n '^mod |^pub mod ' --type rust 2>/dev/null | head -30
```

Look for deep cross-package imports, god modules, and circular import chains.

### 7. Rate and report findings

For each issue, assign severity:

- **Critical** — no CI, no lock files in production apps, secrets in repo, broken build
- **Should Fix** — poor docs, hardcoded config, unclear boundaries, missing tests in CI
- **Nice to Have** — naming inconsistencies, missing ADRs, UX polish

Prioritize actionable feedback. Include specific paths and suggested improvements.

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
