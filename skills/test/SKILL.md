---
name: test
description: Run tests with coverage reporting. Auto-detects test frameworks (Vitest, Playwright, RSpec, pytest, Jest, BATS, etc.) and runs appropriate test commands. Use when asked to run tests, check coverage, or validate code.
---

# Test

Run tests with coverage reporting. This skill auto-detects test frameworks in the project.

## Primary Command

- `uv run lintro tst` - Run tests via lintro (handles multiple frameworks)

## Framework Detection

When lintro is unavailable or you need to run specific test types, detect frameworks by checking for:

| Framework | Config Files | Test Patterns | Run Command |
|-----------|-------------|---------------|-------------|
| **Vitest** | `vitest.config.ts` | `*.test.ts`, `*.spec.ts` | `bun test` or `bunx vitest` |
| **Jest** | `jest.config.js` | `*.test.js`, `*.spec.js` | `bun test` or `bunx jest` |
| **Playwright** | `playwright.config.ts` | `e2e/*.spec.ts` | `bun run e2e` or `bunx playwright test` |
| **RSpec** | `.rspec`, `Gemfile` | `spec/*_spec.rb` | `bundle exec rspec` |
| **pytest** | `pytest.ini`, `pyproject.toml` | `test_*.py`, `*_test.py` | `uv run pytest` |
| **BATS** | `tests/bats/`, `tests/helpers/` | `*.bats` | `bats --recursive tests/bats/` |
| **Go** | `go.mod` | `*_test.go` | `go test ./...` |
| **Rust** | `Cargo.toml` | `#[test]` functions | `cargo test` |

## Rules

- Test runs should ALWAYS generate a coverage report when possible
- New code requires new tests
- Code changes require updated tests
- Check `package.json` scripts for project-specific test commands
- For shell tests, use `/test-shell` skill for detailed BATS guidance

## Usage

When asked to run tests:

1. **Try lintro first:** `uv run lintro tst`
2. **If lintro unavailable or specific tests needed:**
   - Check for config files to detect frameworks
   - Check `package.json` for test scripts
   - Run the appropriate command for each framework
3. **Review coverage reports**
4. **Ensure test coverage for new/modified code**

## Framework-Specific Best Practices

### JavaScript/TypeScript (Vitest/Jest)

```typescript
// Use describe blocks for grouping
describe("UserService", () => {
  it("creates a user with valid data", () => {
    // ...
  });
});
```

### Python (pytest)

Use pytest-style functions, NOT unittest classes:

```python
# CORRECT - pytest function
def test_user_service_creates_user() -> None:
    ...

# Use fixtures and parametrization
@pytest.mark.parametrize("input,expected", [("alice", True), ("", False)])
def test_validate_username(input: str, expected: bool) -> None:
    assert validate_username(input) == expected
```

### Ruby (RSpec)

```ruby
RSpec.describe UserService do
  it "creates a user with valid data" do
    # ...
  end
end
```

### Shell (BATS)

```bash
#!/usr/bin/env bats
load "../helpers/common"

setup() {
    setup_temp_dir
}

teardown() {
    teardown_temp_dir
}

@test "function returns expected value" {
    run my_function "input"
    assert_success
    assert_output "expected"
}
```

### E2E (Playwright)

```typescript
test("user can complete checkout", async ({ page }) => {
  await page.goto("/");
  // Use user-facing locators
  await page.getByRole("button", { name: "Add to cart" }).click();
});
```
