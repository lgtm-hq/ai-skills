# AGENTS

<!-- markdownlint-disable MD013 -->

Canonical skill index for agent-compatible tooling in this repository.

## Quality tooling

Prefer **`uv run lintro chk`** or **`uv run lintro fmt`** when lintro is available;
only use bundled native tools (for example `bandit`, `ruff`, `black`) when lintro is
unavailable or a skill here explicitly overrides that preference.

## Skills

- `analyze-code`: Code-level quality analysis. Use when asked to review code for smells, security issues, implementation quality, or test coverage. (`skills/analyze-code/SKILL.md`)
- `analyze-project`: High-level project analysis. Use when asked to analyze, review, or evaluate a project's architecture, structure, and overall health. (`skills/analyze-project/SKILL.md`)
- `analyze-tests`: Test suite analysis. Use when asked to analyze, review, or evaluate a project's tests for quality, coverage gaps, and best practices. (`skills/analyze-tests/SKILL.md`)
- `branch`: Start work on a new branch or worktree. Use when asked to start a new branch, new worktree, begin work on a feature/fix, or start fresh. Supports issue numbers and plain descriptions. (`skills/branch/SKILL.md`)
- `commit`: Pre-commit workflow and commit guidelines. Use when asked to commit changes. Requires passing lint and tests, signed commits, semantic prefixes, imperative mood. (`skills/commit/SKILL.md`)
- `dashboard-redesign`: Dashboard Redesign — Design vision and implementation guide for the Flowscout SPA dashboard. Use when working on the dashboard restructure, to reload the agreed-upon design direction, tab structure, and remaining tasks. (`skills/dashboard-redesign/SKILL.md`)
- `design`: Create distinctive, production-grade frontend interfaces with high design quality. Use this skill when the user asks to build web components, pages, artifacts, posters, or applications (examples include websites, landing pages, dashboards, React components, HTML/CSS layouts, or when styling/beautifying any web UI). Generates creative, polished code and UI design that avoids generic AI aesthetics. (`skills/design/SKILL.md`)
- `issue`: Create GitHub issues with proper formatting, labels, and AI implementation prompts. Use when asked to create an issue, report a bug, or request a feature. (`skills/issue/SKILL.md`)
- `jira`: Generate Jira-style ticket descriptions. Use when the user says "/jira", "jira ticket", or "give me a Jira ticket". (`skills/jira/SKILL.md`)
- `lint`: Run linting and formatting. Prefer `uv run lintro chk` for checks and `uv run lintro fmt` for formatting when lintro is available; fall back to native tools only when lintro is unavailable or another skill explicitly overrides (e.g. raycast). (`skills/lint/SKILL.md`)
- `lintro-add`: Guide for adding new linting/formatting tools to lintro. Use when implementing shellcheck, shfmt, sqlfluff, taplo, semgrep, gitleaks, or any new tool plugin. (`skills/lintro-add/SKILL.md`)
- `lintro-verify`: Verify that a lintro tool implementation is complete and follows all project standards. Use after adding a new tool to lintro. (`skills/lintro-verify/SKILL.md`)
- `pr`: Create pull requests with proper templates and metadata. Use when asked to create a PR, open a pull request, or submit changes for review. Auto-assign and auto-labeling handled by CI. (`skills/pr/SKILL.md`)
- `pr-raycast`: Prepare and open a pull request to raycast/extensions. Use when the user asks to open, submit, or get ready for a Raycast Store extension PR — not for general extension coding. (`skills/pr-raycast/SKILL.md`)
- `raycast`: Raycast extension development standards. Use when writing or modifying Raycast extensions. Run lintro first, then Raycast's toolchain (npm run lint) which takes precedence for extension-specific rules. (`skills/raycast/SKILL.md`)
- `rebase`: Rebase the current branch onto the latest main. Use when asked to rebase, sync with main, update branch, or pull latest changes. Fetches and rebases onto latest main; does not push automatically. (`skills/rebase/SKILL.md`)
- `reconcile`: Consolidate worktrees and clean up stale branches. Use when asked to reconcile, clean up worktrees, consolidate branches, or tidy up a project's git state. (`skills/reconcile/SKILL.md`)
- `review`: Run CodeRabbit to review code changes. Use when asked to review code, get feedback, or analyze changes. Max 3 runs per change set. (`skills/review/SKILL.md`)
- `scorecard`: Audit the OpenSSF Scorecard rating for py-lintro. Use when asked to check the scorecard, understand the rating, or find what's missing. Specific to github.com/lgtm-hq/py-lintro. (`skills/scorecard/SKILL.md`)
- `stand-ci`: CI/CD and GitHub Actions guidelines. Use when writing workflows or Actions. Shell script code must be in dedicated .sh or .py files. Actions must be pinned to SHAs, not versions. (`skills/stand-ci/SKILL.md`)
- `stand-general`: Global coding standards for all projects and languages. Use when writing any code. Covers linting with lintro, testing with coverage, semantic commits, PR creation, and code review with cr (CodeRabbit CLI). (`skills/stand-general/SKILL.md`)
- `stand-py`: Python >= 3.11 coding standards. Use when writing Python code. Requires type hints, return types, Google-style docstrings, trailing commas, explicit kwargs, StrEnum with auto(), dataclasses, pytest-style tests. (`skills/stand-py/SKILL.md`)
- `stand-rust`: Rust coding standards. Use when writing Rust code. Covers edition, error handling with thiserror/anyhow, unsafe policy, type patterns, testing, documentation, and dependency management. (`skills/stand-rust/SKILL.md`)
- `stand-ts`: TypeScript and JavaScript standards. Use when writing TS/JS code. Covers strict mode, type patterns, error handling, imports, naming, testing, React conventions, and package management with bun. (`skills/stand-ts/SKILL.md`)
- `test`: Run tests with coverage reporting. Auto-detects test frameworks (Vitest, Playwright, RSpec, pytest, Jest, BATS, etc.) and runs appropriate test commands. Use when asked to run tests, check coverage, or validate code. (`skills/test/SKILL.md`)
- `test-api`: Playwright API testing best practices. Use when writing REST API tests with Playwright. Enforces Zod schema validation, client/fixture separation, and contract testing. (`skills/test-api/SKILL.md`)
- `test-shell`: BATS shell script testing. Use when writing or running shell script tests. Covers setup/teardown, assertions, mocking, helper patterns, and coverage with kcov. (`skills/test-shell/SKILL.md`)
- `test-ui`: Playwright E2E testing best practices. Use when writing browser tests, visual regression, or accessibility tests. Enforces user-facing locators, auto-waiting, Page Object Model, and project-specific QSF conventions. (`skills/test-ui/SKILL.md`)
- `turbo-add`: Guide for adding a new theme family to turbo-themes. Use when implementing Nord, Solarized, Gruvbox, Tokyo Night, One Dark, Ayu, Kanagawa, Everforest, Radix, or any new theme. (`skills/turbo-add/SKILL.md`)
- `turbo-test`: Run the full turbo-themes build and test pipeline. Use when asked to build, test, lint, or validate the turbo-themes project. Includes example projects by default. (`skills/turbo-test/SKILL.md`)
- `turbo-verify`: Verify that a theme implementation is complete and follows all project standards. Use after adding a new theme to turbo-themes. (`skills/turbo-verify/SKILL.md`)
- `which-pr`: Report which PR is being worked on in the current conversation. Use when asked about the current PR context. (`skills/which-pr/SKILL.md`)

Total skills: 32

<!-- markdownlint-enable MD013 -->
