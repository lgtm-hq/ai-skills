---
name: test
description: Run tests with coverage reporting. Auto-detects test frameworks (Vitest, Playwright, RSpec, pytest, Jest, BATS, etc.) and runs appropriate test commands. Use when asked to run tests, check coverage, or validate code.
---

# Test

Run tests with coverage reporting. This skill auto-detects test frameworks in the
project.

## Primary Command

- `uv run lintro tst` - Run tests via lintro (handles multiple frameworks)

## Framework Detection

When lintro is unavailable or you need to run specific test types, detect frameworks by
checking for:

| Framework      | Config Files                    | Test Patterns            | Run Command                             |
| -------------- | ------------------------------- | ------------------------ | --------------------------------------- |
| **Vitest**     | `vitest.config.ts`              | `*.test.ts`, `*.spec.ts` | `bun test` or `bunx vitest`             |
| **Jest**       | `jest.config.js`                | `*.test.js`, `*.spec.js` | `bun test` or `bunx jest`               |
| **Playwright** | `playwright.config.ts`          | `e2e/*.spec.ts`          | `bun run e2e` or `bunx playwright test` |
| **RSpec**      | `.rspec`, `Gemfile`             | `spec/*_spec.rb`         | `bundle exec rspec`                     |
| **pytest**     | `pytest.ini`, `pyproject.toml`  | `test_*.py`, `*_test.py` | `uv run pytest`                         |
| **BATS**       | `tests/bats/`, `tests/helpers/` | `*.bats`                 | `bats --recursive tests/bats/`          |
| **Go**         | `go.mod`                        | `*_test.go`              | `go test ./...`                         |
| **Rust**       | `Cargo.toml`                    | `#[test]` functions      | `cargo test`                            |

## Rules

- Check `package.json` scripts for project-specific test commands
- For shell tests, follow the `test-shell` skill for detailed BATS guidance
- Run tests with coverage enabled and include a coverage report in every test run
  (this skill owns the coverage policy)

## Usage

When asked to run tests:

1. **Try lintro first:** `uv run lintro tst`
2. **If lintro unavailable or specific tests needed:**
   - Check for config files to detect frameworks
   - Check `package.json` for test scripts
   - Run the appropriate command for each framework
3. **Review coverage reports**
4. **Ensure test coverage for new/modified code**

## Writing Tests

For how to write tests, delegate to the appropriate skill:

| Stack / tool                        | Skill        |
| ----------------------------------- | ------------ |
| Python (pytest)                     | `stand-py`   |
| TypeScript/JavaScript (Vitest/Jest) | `stand-ts`   |
| Rust (`cargo test`)                 | `stand-rust` |
| Shell (BATS)                        | `test-shell` |
| Playwright E2E                      | `test-ui`    |
| Playwright API                      | `test-api`   |

For other frameworks (RSpec, Go), follow project conventions and the patterns detected
above.
