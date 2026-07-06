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
- `babysit-pr`: Autonomously drive an open PR to merge-ready state by triaging Greptile and CodeRabbit review comments, fixing CI failures, handling CodeRabbit rate limits, and looping until checks are green with no unresolved actionable threads. Use when asked to babysit a PR, shepherd a PR, or keep a PR merge-ready until review/CI cycles complete. (`skills/babysit-pr/SKILL.md`)
- `branch`: Start work on a new branch or worktree. Use when asked to start a new branch, new worktree, begin work on a feature/fix, or start fresh. Supports issue numbers and plain descriptions. (`skills/branch/SKILL.md`)
- `coderabbit`: Run CodeRabbit CLI for pre-push AI diff review. Use when asked for CodeRabbit, cr review, or as part of the default dual pre-push workflow with greptile. Max 2-3 runs per change set. (`skills/coderabbit/SKILL.md`)
- `commit`: Pre-commit workflow and commit guidelines. Use when asked to commit changes. Requires passing lint and tests, signed commits, semantic prefixes, imperative mood. (`skills/commit/SKILL.md`)
- `design`: Create distinctive, production-grade frontend interfaces with high design quality. Use this skill when the user asks to build web components, pages, artifacts, posters, or applications (examples include websites, landing pages, dashboards, React components, HTML/CSS layouts, or when styling/beautifying any web UI). Generates creative, polished code and UI design that avoids generic AI aesthetics. (`skills/design/SKILL.md`)
- `greptile`: Run Greptile CLI for pre-push AI branch review. Use when asked for Greptile review, raycast/extensions pre-PR checks, or as part of the default dual pre-push workflow with coderabbit. Max 2 runs per change set. (`skills/greptile/SKILL.md`)
- `implement-issues`: Implement a set of GitHub issues in parallel - triage or take an explicit issue list, group by file-conflict, create a worktree per lane, delegate to sub-agents, open a PR per lane; never merges. Use when asked to implement issues, work the backlog, or pick up multiple issues in parallel. (`skills/implement-issues/SKILL.md`)
- `issue`: Create GitHub issues with proper formatting, labels, and AI implementation prompts. Use when asked to create an issue, report a bug, or request a feature. (`skills/issue/SKILL.md`)
- `jira`: Generate Jira-style ticket descriptions. Use when the user says "/jira", "jira ticket", or "give me a Jira ticket". (`skills/jira/SKILL.md`)
- `lint`: Run linting and formatting. Prefer `uv run lintro chk` for checks and `uv run lintro fmt` for formatting when lintro is available; fall back to native tools only when lintro is unavailable or another skill documents a follow-up pass (e.g. raycast). (`skills/lint/SKILL.md`)
- `lintro-add`: Guide for adding new linting/formatting tools to lintro. Use when implementing shellcheck, shfmt, sqlfluff, taplo, semgrep, gitleaks, or any new tool plugin. (`skills/lintro-add/SKILL.md`)
- `lintro-verify`: Verify that a lintro tool implementation is complete and follows all project standards. Use after adding a new tool to lintro. (`skills/lintro-verify/SKILL.md`)
- `pr`: Create pull requests with proper templates and metadata. Use when asked to create a PR, open a pull request, or submit changes for review. Auto-assign and auto-labeling handled by CI. (`skills/pr/SKILL.md`)
- `pr-raycast`: Prepare and open a pull request to raycast/extensions. Use when the user asks to open, submit, or get ready for a Raycast Store extension PR — not for general extension coding. (`skills/pr-raycast/SKILL.md`)
- `raycast`: Raycast extension development standards. Use when writing or modifying Raycast extensions. Run lintro first, then Raycast's toolchain (npm run lint) which takes precedence for extension-specific rules. (`skills/raycast/SKILL.md`)
- `rebase`: Rebase the current branch onto the latest main. Use when asked to rebase, sync with main, update branch, or pull latest changes. Fetches and rebases onto latest main; does not push automatically. (`skills/rebase/SKILL.md`)
- `reconcile`: Consolidate worktrees and clean up stale branches. Use when asked to reconcile, clean up worktrees, consolidate branches, or tidy up a project's git state. (`skills/reconcile/SKILL.md`)
- `scorecard`: Audit the OpenSSF Scorecard rating for py-lintro. Use when asked to check the scorecard, understand the rating, or find what's missing. Specific to github.com/lgtm-hq/py-lintro. (`skills/scorecard/SKILL.md`)
- `stand-ci`: CI/CD and GitHub Actions guidelines. Use when writing workflows or Actions. Shell script code must be in dedicated .sh or .py files. Actions must be pinned to SHAs, not versions. (`skills/stand-ci/SKILL.md`)
- `stand-general`: Global coding standards for all projects and languages. Use when writing any code. Covers linting with lintro, testing with coverage, semantic commits, PR creation, and pre-push AI review with coderabbit and greptile CLIs. (`skills/stand-general/SKILL.md`)
- `stand-odin`: Odin coding standards. Use when writing Odin code. Covers idiomatic error handling with or_else and or_return, memory/allocator patterns, attributes, naming and API conventions, and testing with core:testing. (`skills/stand-odin/SKILL.md`)
- `stand-py`: Python >= 3.11 coding standards. Use when writing Python code. Requires type hints, return types, Google-style docstrings, trailing commas, explicit kwargs, StrEnum with auto(), dataclasses, pytest-style tests. (`skills/stand-py/SKILL.md`)
- `stand-rust`: Rust coding standards. Use when writing Rust code. Covers edition, error handling with thiserror/anyhow, unsafe policy, type patterns, testing, documentation, and dependency management. (`skills/stand-rust/SKILL.md`)
- `stand-ts`: TypeScript and JavaScript standards. Use when writing TS/JS code. Covers strict mode, type patterns, error handling, imports, naming, testing, React conventions, and package management with bun. (`skills/stand-ts/SKILL.md`)
- `test`: Run tests with coverage reporting. Auto-detects test frameworks (Vitest, Playwright, RSpec, pytest, Jest, BATS, etc.) and runs appropriate test commands. Use when asked to run tests, check coverage, or validate code. (`skills/test/SKILL.md`)
- `test-api`: Playwright API testing best practices. Use when writing REST API tests with Playwright. Enforces Zod schema validation, client/fixture separation, and contract testing. (`skills/test-api/SKILL.md`)
- `test-shell`: BATS shell script testing. Use when writing or running shell script tests. Covers setup/teardown, assertions, mocking, helper patterns, and coverage with kcov. (`skills/test-shell/SKILL.md`)
- `test-ui`: Playwright E2E testing best practices. Use when writing browser tests, visual regression, or accessibility tests in any project. Enforces user-facing locators, auto-waiting, web-first assertions, and Page Object Model. (`skills/test-ui/SKILL.md`)
- `test-ui-qsf`: QSF project conventions for the Playwright E2E suite. Use when working in the QSF playwright-tests directory (authFixtures, ___ping-* handles, data-test-label test IDs, .auth storage states) — not for generic Playwright advice. (`skills/test-ui-qsf/SKILL.md`)
- `turbo-add`: Guide for adding a new theme family to turbo-themes. Use when implementing Nord, Solarized, Gruvbox, Tokyo Night, One Dark, Ayu, Kanagawa, Everforest, Radix, or any new theme. (`skills/turbo-add/SKILL.md`)
- `turbo-test`: Run the full turbo-themes build and test pipeline. Use when asked to build, test, lint, or validate the turbo-themes project. Includes example projects by default. (`skills/turbo-test/SKILL.md`)
- `turbo-verify`: Verify that a theme implementation is complete and follows all project standards. Use after adding a new theme to turbo-themes. (`skills/turbo-verify/SKILL.md`)
- `which-pr`: Report which PR is being worked on in the current conversation. Use when asked about the current PR context. (`skills/which-pr/SKILL.md`)

Total skills: 36

<!-- markdownlint-enable MD013 -->
