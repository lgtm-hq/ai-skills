---
name: test-ui
description: Playwright E2E testing best practices. Use when writing browser tests, visual regression, or accessibility tests in any project. Enforces user-facing locators, auto-waiting, web-first assertions, and Page Object Model.
---

# Playwright E2E Testing Standards

Write and maintain browser E2E tests following Playwright best practices. These
rules are project-agnostic; project-specific conventions (fixtures, test IDs,
config) live in the project's own skill — for the QSF suite, follow the
`test-ui-qsf` skill alongside this one.

## Locators (Priority Order)

Use user-facing locators.

```typescript
// BEST: Semantic locators
page.getByRole("button", { name: "Submit" });
page.getByRole("tab", { name: "Dashboard" });
page.getByLabel("Email");
page.getByPlaceholder("Search...");
page.getByText("Welcome");
page.getByTitle("Document title");

// GOOD: Test IDs (attribute set by testIdAttribute in playwright.config.ts)
page.getByTestId("delete-row-btn");

// ACCEPTABLE: CSS locators for structural queries
page.locator('input[type="file"][multiple]');

// AVOID: Fragile CSS selectors
page.locator("#submit-btn");
page.locator("div > button.primary");
```

## Auto-Waiting

Never use `waitForTimeout()`. Playwright auto-waits for elements.

```typescript
// WRONG: Manual timeouts
await page.waitForTimeout(1000);
await button.click();

// CORRECT: Auto-waiting assertions
await expect(button).toBeVisible();
await button.click();

// CORRECT: Poll for async state
await expect
  .poll(async () => page.evaluate(() => localStorage.getItem("theme")))
  .toBe("dark");

// CORRECT: Wait for specific conditions
await page.waitForLoadState("networkidle");
await page.waitForURL(/\/dashboard/);

// ACCEPTABLE: toPass() for polling complex async operations
await expect(async () => {
  await dashboardPage.open();
  await dashboardPage.assertPresent();
}).toPass({ timeout: 30_000 });
```

## Web-First Assertions

Use Playwright's auto-retrying assertions. Keep assertions in page objects where
possible.

```typescript
// CORRECT: Web-first (auto-retries)
await expect(page.getByRole("heading")).toHaveText("Dashboard");
await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
await expect(button).toBeEnabled();

// CORRECT: Page object assertion methods
await dashboardPage.assertSelectedCheckboxes(["Odd", "Free"]);

// AVOID: Manual checks (no retry)
const text = await heading.textContent();
expect(text).toBe("Dashboard");
```

## Page Object Model

Use a `BasePage → SpecializedPage` hierarchy with composed components.

```typescript
// pageObjects/BasePage.ts — all pages extend this
export default class BasePage {
  public navigation = new Navigation(this.page);

  constructor(readonly page: Page) {}

  async openTab(tabName: string): Promise<void> {
    await this.page.getByRole("tab", { name: tabName }).click();
  }

  async assertUrl(path: string | RegExp): Promise<void> {
    await expect(this.page).toHaveURL(path);
  }
}

// pageObjects/DetailPage.ts — specialized page
export default class DetailPage extends BasePage {
  public fileUploadComponent = new FileUpload(this.page);

  readonly errorLabel: Locator = this.page.getByRole("alert");

  async assertError(message?: string): Promise<void> {
    await expect(this.errorLabel).toBeVisible();
    if (message) await expect(this.errorLabel).toHaveText(message);
  }
}
```

### Rules

- **One class per page/component** — keep files focused
- **Locators as `readonly` properties** — defined in constructor scope, not in
  methods
- **Assertions belong in page objects** — prefix with `assert`
- **Actions return `Promise<void>`** — no chaining
- **Compose via child components** — `this.navigation`,
  `this.fileUploadComponent`, etc.
- **Split large element libraries** — keep shared element classes under ~300
  lines, one file per element type

## Test Design

- Tests are independent — no shared mutable state between tests
- Use `forEach` loops over arrays/objects for data-driven parameterization
- Test names describe the scenario and expected outcome
- Extract `beforeEach` navigation to shared helpers when duplicated 3+ times
- No `console.log` debug output — use `test.step()` annotations
- Import UI labels, error messages, and identifiers from constants/enums — never
  hard-code strings in tests

## Known Anti-Patterns

### 1. Mutable global state across tests

```typescript
// BAD: shared array mutated across iterations — creates order dependency
const passedTests: string[] = [];
for (const tc of testcases) {
  test(`test ${tc}`, async () => {
    passedTests.push(tc);
  });
}

// GOOD: each test is self-contained
testcases.forEach((tc) => {
  test(`test ${tc}`, async ({ page }) => {
    // no shared mutable state
  });
});
```

### 2. Test name doesn't match behavior

Name the test after what it actually asserts, not the component you started with.

### 3. Visibility-only assertions ("nothing burger" tests)

```typescript
// BAD: only checks the element exists — passes even if broken
await detailPage.assertBadgeVisible("Theme");

// GOOD: verify content and interaction
await detailPage.assertBadgeText("Theme", "Default");
await detailPage.selectBadge("Theme", "Dark");
await detailPage.assertBadgeText("Theme", "Dark");
```

## Network Interception

```typescript
// Mock API responses
await page.route("**/api/user", (route) => {
  route.fulfill({ json: { name: "Test User" } });
});

// Simulate failures
await page.route("**/*.css", (route) => route.abort("failed"));

// Cleanup after test — unroute every mock you registered
await page.unroute("**/api/user");
await page.unroute("**/*.css");
```

## Checklist

- [ ] Locators use `getByRole`, `getByTestId`, `getByLabel`, `getByTitle` (not
      fragile CSS)
- [ ] No `waitForTimeout()` calls — auto-waiting assertions only
- [ ] Assertions are web-first (`expect()` auto-retrying), meaningful beyond
      visibility checks
- [ ] Page objects extend the base page, compose components, keep locators as
      `readonly` properties, and own the `assert*` methods
- [ ] Tests independent; `forEach` parameterization; descriptive names
- [ ] No debug logging; constants imported, not hard-coded
