---
name: raycast
description: Raycast extension development standards. Use when writing or modifying Raycast extensions. Overrides default linting to use Raycast's toolchain (ray lint) instead of lintro.
---

# Raycast Extension Development

Standards for developing Raycast extensions. **These override the global `standards` skill when working in Raycast extension directories.**

## Linting & Formatting

**IMPORTANT:** Do NOT use `lintro` for Raycast extensions. Use Raycast's native toolchain:

```bash
# Check for issues
bun run lint        # or: ray lint

# Auto-fix issues
bun run fix-lint    # or: ray lint --fix

# Build extension
bun run build       # or: ray build -e dist

# Development mode
bun run dev         # or: ray develop
```

Raycast uses:
- ESLint with `@raycast/eslint-config`
- Prettier for formatting
- TypeScript strict mode

## Package Management

- Use `bun` instead of `npm` (per CLAUDE.md)
- Install: `bun install`
- Run scripts: `bun run <script>`

## Project Structure

Follow modular architecture with small, focused files:

```
src/
├── <command>.tsx           # One file per command
├── components/             # Reusable React components
│   └── <component>.tsx
├── hooks/                  # Custom React hooks
│   └── use-<name>.ts
├── lib/                    # Utility modules
│   ├── <feature>.ts
│   └── validation.ts
└── types/
    └── index.ts            # Shared TypeScript types
```

## Commands

Each command is a separate entry point in `package.json`:

```json
{
  "commands": [
    {
      "name": "index",           // Matches src/index.tsx
      "title": "Command Title",
      "description": "What it does",
      "mode": "view"             // or "no-view" for background
    }
  ]
}
```

## API Patterns

### File Selection
```typescript
import { getSelectedFinderItems } from "@raycast/api";

const items = await getSelectedFinderItems();
const paths = items.map(item => item.path);
```

### Toast Notifications
```typescript
import { showToast, Toast } from "@raycast/api";

// Success
await showToast({ style: Toast.Style.Success, title: "Done" });

// Error
await showToast({ style: Toast.Style.Failure, title: "Error", message: details });

// Loading
await showToast({ style: Toast.Style.Animated, title: "Working..." });
```

### Confirmation Dialogs
```typescript
import { confirmAlert, Alert } from "@raycast/api";

const confirmed = await confirmAlert({
  title: "Delete Item?",
  message: "This cannot be undone",
  primaryAction: {
    title: "Delete",
    style: Alert.ActionStyle.Destructive,
  },
});
```

### Local Storage
```typescript
import { LocalStorage } from "@raycast/api";

await LocalStorage.setItem("key", JSON.stringify(data));
const raw = await LocalStorage.getItem<string>("key");
const data = raw ? JSON.parse(raw) : defaultValue;
```

### Cached State (persists across invocations)
```typescript
import { useCachedState } from "@raycast/utils";

const [value, setValue] = useCachedState<boolean>("key", false);
```

## Contributing to Existing Extensions

When contributing to extensions you don't own:

1. **Add yourself to contributors** in `package.json`
2. **Update CHANGELOG.md** with `{PR_MERGE_DATE}` placeholder
3. **Run lint and build** before committing
4. **Create PR** to `raycast/extensions` repo

## Testing

Raycast extensions don't have a standard test framework. For testable logic:

1. Extract pure functions to `lib/` modules
2. Test with Vitest if needed (add as devDependency)
3. Manual testing via `bun run dev`

## Version Bumping

- Patch (1.0.x): Bug fixes
- Minor (1.x.0): New features, backwards compatible
- Major (x.0.0): Breaking changes

## Constraints

- Max 12 keywords in `package.json`
- Max filename length: 255 characters (macOS)
- Avoid synchronous file operations (use `fs/promises`)
- Don't use AppleScript for file operations (security risk)

## Store Submission / PR Readiness Checklist

Before opening a PR to `raycast/extensions`, verify every item below.

### Package.json

- Required fields: `name`, `title`, `description`, `icon`, `author`, `platforms`, `categories`, `license` (must be `"MIT"`)
- `commands` array with `name`, `title`, `description`, `mode` for each command
- Command titles in Title Case (Apple Style Guide)
- Required scripts: `build`, `dev`, `lint`, `fix-lint`, `publish`
- `publish` script: `npx @raycast/api@latest publish`
- Max 12 keywords
- No manual `Preferences` interfaces — use auto-generated types from `raycast-env.d.ts`

### Build & Lint

- `npm run build` passes (use npm, not bun, for final validation)
- `npm run lint` passes (ESLint + Prettier)
- Prettier config: `printWidth: 120`, `singleQuote: false`

### Lock Files

- `package-lock.json` must exist (npm)
- No `bun.lock`, `bun.lockb`, `yarn.lock`, or `pnpm-lock.yaml` committed
- Root `.gitignore` of `raycast/extensions` already blocks non-npm lockfiles

### Icon

- 512x512 PNG in `assets/`
- Works on both light and dark backgrounds
- Not the default Raycast icon
- Referenced in `package.json` `icon` field

### Screenshots

- Located in `metadata/` directory
- Named `{extension-name}-{N}.png` (e.g., `renaming-1.png`)
- Dimensions: 2000x1250 PNG (16:10 landscape)
- Maximum 6 screenshots
- Consistent background and appearance across all screenshots
- No sensitive data visible
- Don't mix light and dark themes

### CHANGELOG.md

- Exists at extension root
- New version entry uses `{PR_MERGE_DATE}` as the date placeholder (never hardcode dates)
- For updates to existing extensions: add NEW entries at the top, never modify existing entries
- Entries must accurately reflect implemented features (no phantom features)

### README.md

- Required if extension needs setup instructions (API keys, auth, etc.)
- Documents only features that actually exist in the codebase
- Examples are consistent with actual behavior
- Media files referenced in README go in a `media/` folder (not `metadata/`)

### Code Quality

- Use `trash()` instead of `unlink()` for file deletion
- Use `fs/promises` (async), not synchronous `fs` operations
- No AppleScript for file operations (security risk)
- US English only in all user-facing strings
- No custom Preferences interfaces (use auto-generated from `raycast-env.d.ts`)
- No unused files in `assets/` directory

### PR Submission

- PR title format: `Extension Name: Brief description`
- Include a screencast or screenshot in PR description
- Label: `extension fix / improvement` for updates, `new extension` for new extensions
- Greptile bot auto-checks: CHANGELOG date format, Preferences interfaces, Prettier config
- Human reviewers check: screenshot consistency, changelog entries, visual expression
- Respond to review feedback promptly — 14 days no activity marks PR stale, 21 days auto-closes
