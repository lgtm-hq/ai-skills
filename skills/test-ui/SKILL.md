---
name: test-ui
description: Playwright E2E testing best practices. Use when writing browser tests, visual regression, or accessibility tests. Enforces user-facing locators, auto-waiting, Page Object Model, and project-specific QSF conventions.
---

# Playwright E2E Testing Standards

Write and maintain browser E2E tests following Playwright best practices and
project-specific conventions.

## Commands

- `source ./bin/load_env.sh && npx playwright test` - Run all tests headless
- `source ./bin/load_env.sh && npx playwright test --project=regression-tests` - Skip
  auth-setup
- `bun run test` / `npx playwright test --ui` - Interactive UI mode
- `npx playwright test --reporter=list` - Verbose terminal output
- `npx playwright test --grep @smoke` - Run tagged tests
- `npx playwright show-trace <trace.zip>` - Inspect failure traces

## Locators (Priority Order)

Use user-facing locators. The project uses `data-test-label` as the custom test ID
attribute (configured in `playwright.config.ts`).

```typescript
// BEST: Semantic locators
page.getByRole("button", { name: "Submit" });
page.getByRole("tab", { name: "Dashboard" });
page.getByLabel("Email");
page.getByPlaceholder("Search...");
page.getByText("Welcome");
page.getByTitle("___ping-files-en");

// GOOD: Test IDs (resolves to data-test-label attribute)
page.getByTestId("no-handles-available-indicator");
page.getByTestId("delete-row-btn");
page.getByTestId("open-filter-section-button");

// ACCEPTABLE: CSS locators for structural queries
page.locator(".ap-notifications");
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
  .poll(async () => {
    return await page.evaluate(() => localStorage.getItem("theme"));
  })
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
await expect(dialog).toBeVisible();

// CORRECT: Page object assertion methods
await appsDetailPage.assertHandleError("produced an error");
await myAppsPage.assertVisibleHandles(expectedHandles);
await dashboardPage.assertSelectedCheckboxes(["Odd", "Free"]);

// AVOID: Manual checks (no retry)
const text = await heading.textContent();
expect(text).toBe("Dashboard");
```

## Page Object Model (Project Pattern)

This project uses a `BasePage → SpecializedPage` hierarchy with composed components.

### Base Page Pattern

```typescript
// pageObjects/BasePage.ts — All pages extend this
export default class BasePage {
  public navigation = new Navigation(this.page);
  public filterSection = new FilterSection(this.page);
  public idleModal = new IdleModal(this.page);

  constructor(readonly page: Page) {}

  async openTab(tabName: string): Promise<void> {
    await this.page.getByRole("tab", { name: tabName }).click();
  }

  async assertUrl(path: string | RegExp): Promise<void> {
    await expect(this.page).toHaveURL(path);
  }
}
```

### Specialized Page Pattern

```typescript
// pageObjects/AppsDetailPage.ts
export default class AppsDetailPage extends BasePage {
  public fileUploadComponent = new FileUpload(this.page);
  public iwaComponent = new Iwa(this.page);

  readonly errorLabel: Locator = this.page.locator(".ap-notifications");

  async assertHandleError(errorMessage?: string): Promise<void> {
    await expect(this.errorLabel).toBeVisible({ timeout: 90000 });
    if (errorMessage) await expect(this.errorLabel).toHaveText(errorMessage);
  }
}
```

### Rules

- **One class per page/component** — keep files focused
- **Locators as `readonly` properties** — defined in constructor scope, not in methods
- **Assertions belong in page objects** — prefix with `assert` (e.g.,
  `assertDashboard()`, `assertHandleError()`)
- **Actions return `Promise<void>`** — no chaining
- **Compose via child components** — `this.navigation`, `this.fileUploadComponent`, etc.
- **FormElements.ts should stay under 300 lines** — split large element libraries into
  separate files per element type

## Fixtures (Auth Pattern)

The project extends Playwright's `test` with pre-authenticated user fixtures via storage
state files.

```typescript
// fixtures/authFixtures.ts
import path from "node:path";

import { test as baseTest, Browser, Page } from "@playwright/test";

const authFiles = {
  guest: "guest_storage_state.json",
  testView: "test_view_storage_state.json",
  testNoRights: "test_no_rights_storage_state.json",
  // ... more users
};

const baseFixtures = Object.fromEntries(
  Object.entries(authFiles).map(([key, fileName]) => [
    key,
    async (
      { browser }: { browser: Browser },
      use: (page: Page) => Promise<void>,
    ) => {
      const storageState = path.join(__dirname, "../.auth", fileName);
      const context = await browser.newContext({ storageState });
      const page = await context.newPage();
      await use(page);
      await context.close();
    },
  ]),
);

export const test = baseTest.extend(baseFixtures);
export const expect = test.expect;
```

### Fixture Usage

```typescript
// Tests import from authFixtures, NOT from @playwright/test
import { test, expect } from "../../fixtures/authFixtures";

test("user sees their handles", async ({ guest }) => {
  // `guest` is a pre-authenticated Page — no login needed
  await guest.goto("/");
  // ...
});

test("restricted user cannot access admin", async ({ testNoRights }) => {
  await testNoRights.goto("/admin");
  // ...
});
```

## Test Structure & Organization

### File Organization

```text
playwright-tests/
├── .auth/              # Storage state JSON files (gitignored in CI)
├── enums/              # Constants: handle names, error messages, labels
├── fixtures/           # authFixtures.ts — extended test/expect
├── pageObjects/        # POM classes (BasePage, LoginPage, etc.)
│   └── components/     # Reusable: Navigation, FileUpload, FormElements
├── setup/              # auth.setup.ts, cleanup.ts
└── tests/              # Spec files grouped by feature
    ├── handle/
    ├── login-logout/
    ├── ping-files/
    ├── ping-form-files/
    ├── ping-forms-v2/
    ├── ping-iwa/
    ├── user-interface/
    └── user-rights.spec.ts
```

### Test File Pattern

```typescript
import { test, expect } from "../../fixtures/authFixtures";
import { MyAppsPage } from "../../pageObjects/MyAppsPage";
import { HandleNames } from "../../enums/handles";

test.describe("Feature Area", () => {
  test.beforeEach(async ({ guest }) => {
    const myAppsPage = new MyAppsPage(guest);
    await guest.goto("/");
    await myAppsPage.navigation.openHandle(HandleNames.PING_FILES);
  });

  test("describes expected behavior", async ({ guest }) => {
    // Arrange — already done in beforeEach
    // Act
    await appsDetailPage.doSomething();
    // Assert — use page object assertion methods
    await appsDetailPage.assertSomething(expected);
  });
});
```

### Parameterized Tests

Use `forEach` loops for data-driven tests. This is the project's established pattern.

```typescript
// GOOD: Array-driven parameterization
const testcases = ["tc01", "tc02", "tc03", "tc04", "tc05"];
testcases.forEach((testcase) => {
  test(`ping file handle tests: ${testcase}`, async ({ guest }) => {
    const myAppsPage = new MyAppsPage(guest);
    await guest.goto("/");
    await myAppsPage.navigation.openHandle(HandleNames.PING_FILES);
    // ... test logic using testcase
  });
});

// GOOD: Object-driven with expected values
const cases = [
  { component: "Activity per Month", expectedOptions: ["PDF", "PNG"] },
  { component: "Pie Chart", expectedOptions: ["PDF", "SVG"] },
];
cases.forEach(({ component, expectedOptions }) => {
  test(`Export options for ${component}`, async ({ guest }) => {
    await dashboardPage.assertExportOptions(component, expectedOptions);
  });
});
```

### Environment-Aware Tests

```typescript
import { isOpenAmEnv } from "../../src/utils/environment";

test.skip(isOpenAmEnv === true, "This test is only for Keycloak environments");
test.skip(isOpenAmEnv, "Not applicable in OpenAM environment");
```

## Configuration

```typescript
// playwright.config.ts
export default defineConfig({
  testDir: "./playwright-tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.TEST_HANDLE ? 0 : 1,
  workers: process.env.CI ? 1 : 5,
  reporter: "html",
  globalTimeout: 30 * 60 * 1000,
  timeout: 60000,
  expect: { timeout: 10000 },
  use: {
    ignoreHTTPSErrors: true,
    testIdAttribute: "data-test-label", // Custom test ID attribute
    baseURL: envUrl,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "auth-setup",
      testMatch: "**/setup/auth.setup.ts",
      use: { headless: true },
    },
    {
      name: "regression-tests",
      testMatch: ["**/tests/*.spec.ts", "**/tests/**/*.spec.ts"],
      dependencies: process.env.CI ? ["auth-setup"] : [],
      use: { trace: "retain-on-failure", headless: true },
    },
  ],
});
```

## Enums & Constants

Store UI labels, error messages, and handle identifiers in `playwright-tests/enums/`.

```typescript
// enums/handles.ts
export const HandleNames = { PING_FILES: '___ping-files-en', ... };
export const HandleIds = { PING_FILES: 'qsf-handle-ping-files', ... };

// enums/errors.ts
export const Errors = { FILE_TOO_LARGE: 'produced an error while processing', ... };

// enums/elementLabels.ts
export const Buttons = { SUBMIT: 'Submit', UPLOAD: 'Upload files', ... };
```

**Never hard-code** handle names, error messages, or button labels in tests. Import from
enums.

## Known Anti-Patterns to Avoid

### 1. Mutable global state across tests

```typescript
// BAD: Shared mutable state between test iterations
const passedTests: string[] = [];
for (const tc of testcases) {
  test(`test ${tc}`, async () => {
    // ... modifies passedTests — creates order dependency
    passedTests.push(tc);
  });
}

// GOOD: Each test is independent
testcases.forEach((tc) => {
  test(`test ${tc}`, async ({ guest }) => {
    // Self-contained — no shared mutable state
  });
});
```

### 2. Debug logging left in tests

```typescript
// BAD: console.log left in test code
console.log("Initial Content:", initialContent);
console.log("Cleaned:", cleanedContent);

// GOOD: Use test.info() or step annotations for debugging
await test.step("verify initial content", async () => {
  await expect(table).toHaveText(expectedContent);
});
```

### 3. Test name doesn't match behavior

```typescript
// BAD: Name says filterPill but tests card
test("IWA filterPill tests", async ({ guest }) => {
  await appsDetailPage.iwaComponent.assertCardVisible("Title");
});

// GOOD: Name matches what's tested
test("IWA card component is visible with correct title", async ({ guest }) => {
  await appsDetailPage.iwaComponent.assertCardVisible("Title");
});
```

### 4. Visibility-only assertions ("nothing burger" tests)

```typescript
// BAD: Only checks element exists — would pass even if broken
test("badge works", async ({ guest }) => {
  await appsDetailPage.iwaComponent.assertBadgeVisible("Theme");
});

// GOOD: Verify behavior, content, and interaction
test("badge displays theme label and updates on selection", async ({
  guest,
}) => {
  await appsDetailPage.iwaComponent.assertBadgeVisible("Theme");
  await appsDetailPage.iwaComponent.assertBadgeText("Theme", "Default");
  await appsDetailPage.iwaComponent.selectBadge("Theme", "Dark");
  await appsDetailPage.iwaComponent.assertBadgeText("Theme", "Dark");
});
```

### 5. Duplicated beforeEach navigation

```typescript
// BAD: Copy-pasted in every describe block
test.beforeEach(async ({ guest }) => {
  const myAppsPage = new MyAppsPage(guest);
  await guest.goto("/");
  await myAppsPage.navigation.openHandle(HandleNames.PING_FILES);
  appsDetailPage = new AppsDetailPage(guest);
  await appsDetailPage.fileUploadComponent.uploadFilesFromTestCase(
    handle,
    "tc18",
  );
  await appsDetailPage.fileUploadComponent.submitFileUpload();
  dashboardPage = new DashboardPage(guest);
  await dashboardPage.assertDashboard();
});

// GOOD: Extract to a fixture or shared helper
async function setupDashboardForTestcase(
  guest: Page,
  handleName: string,
  testcase: string,
): Promise<DashboardPage> {
  const myAppsPage = new MyAppsPage(guest);
  await guest.goto("/");
  await myAppsPage.navigation.openHandle(handleName);
  const appsDetailPage = new AppsDetailPage(guest);
  await appsDetailPage.fileUploadComponent.uploadFilesFromTestCase(
    handleName,
    testcase,
  );
  await appsDetailPage.fileUploadComponent.submitFileUpload();
  const dashboardPage = new DashboardPage(guest);
  await dashboardPage.assertDashboard();
  return dashboardPage;
}
```

## Network Interception

```typescript
// Mock API responses
await page.route("**/api/user", (route) => {
  route.fulfill({ json: { name: "Test User" } });
});

// Simulate failures
await page.route("**/*.css", (route) => {
  route.abort("failed");
});

// Cleanup after test
await page.unroute("**/api/user");
```

## Checklist

### Locators & Assertions

- [ ] Locators use `getByRole`, `getByTestId`, `getByLabel`, `getByTitle` (not fragile
      CSS)
- [ ] `getByTestId` resolves to `data-test-label` attribute (project config)
- [ ] No `waitForTimeout()` calls — use auto-waiting assertions
- [ ] Assertions use `expect()` from Playwright (web-first, auto-retrying)
- [ ] Tests have meaningful assertions beyond just visibility checks

### Page Objects

- [ ] Page objects extend `BasePage` and compose child components
- [ ] Locators are `readonly` properties, not created inside methods
- [ ] Assertion methods prefixed with `assert` live in page objects
- [ ] FormElements classes stay focused — split if >300 lines

### Test Design

- [ ] Tests are independent — no shared mutable state between tests
- [ ] Use `forEach` parameterization for data-driven test cases
- [ ] Test names clearly describe the scenario and expected outcome
- [ ] `beforeEach` navigation extracted to shared helpers when duplicated 3+ times
- [ ] No `console.log` debug output left in test code
- [ ] Constants imported from `enums/` — no hard-coded strings in tests

### Fixtures & Auth

- [ ] Import `test` and `expect` from `authFixtures`, not `@playwright/test`
- [ ] Use named user fixtures (`guest`, `testView`, `testNoRights`) for auth
- [ ] Browser context closed after each fixture via `context.close()`

### Environment

- [ ] Use `test.skip(isOpenAmEnv, ...)` for environment-specific tests
- [ ] Env loaded via `source ./bin/load_env.sh` before running
- [ ] `ENVIRONMENT` variable controls target URL (default: `test`)
