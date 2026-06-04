---
name: raycast
description: Raycast extension development standards. Use when writing or modifying Raycast extensions. Run lintro first, then Raycast's toolchain (npm run lint) which takes precedence for extension-specific rules.
---

# Raycast Extension Development

## Scope

Use when **writing or modifying** a Raycast extension. To **open or prepare a PR** to
[raycast/extensions](https://github.com/raycast/extensions), use **`pr-raycast`** instead.

Overrides global lint/commit defaults in extension directories.

## Official resources

- [Prepare for Store](https://developers.raycast.com/basics/prepare-an-extension-for-store)
- [Screenshots](https://developers.raycast.com/basics/prepare-an-extension-for-store#screenshots)
- [Icon Maker](https://icon.ray.so/)
- [Publish](https://developers.raycast.com/basics/publish-an-extension)
- [Extension Guidelines](https://manual.raycast.com/extensions-guidelines)

## Linting & Formatting

**Order:** lintro first → Raycast last. Raycast wins on conflicts.

```bash
# 1. Repo root (when lintro is configured)
uv run lintro fmt && uv run lintro chk

# 2. extensions/<name>/ — required before commit
npm run lint
npm run fix-lint && npm run lint   # only if lint failed
npm run build                      # distribution build; CI uses npm
bun run dev                        # local dev only
```

Prettier: `printWidth: 120`, `singleQuote: false`. ESLint: `@raycast/eslint-config`.

## Package Management

- Local dev: `bun install`, `bun run <script>`
- CI/store validation: `npm run lint`, `npm run build`

## Project Structure

```text
src/
├── <command>.tsx
├── components/
├── hooks/
├── lib/
└── types/
```

One command file per `package.json` commands entry. Extract testable logic to `lib/`.
Vitest optional; manual test via `bun run dev`.

## Code patterns

- `getPreferenceValues<Preferences.<Command>>()` — never manual `Preferences` interfaces
- `trash()` for user file deletion; `fs/promises` only (no sync fs, no AppleScript)
- `execFile` with arg arrays — no shell string interpolation for paths

## Constraints

- Max 12 keywords; MIT license; US English UI strings
- Max filename length 255 (macOS)

## Store readiness checklist

Verify before asking to open a PR (full workflow in **`pr-raycast`**).

### package.json

- Fields: `name`, `title`, `description`, `icon`, `author`, `platforms`, `categories`,
  `license: MIT`
- Scripts: `build`, `dev`, `lint`, `fix-lint`, `publish` (`npx @raycast/api@latest publish`)
- Command titles: Title Case (Apple Style Guide)
- `package-lock.json` committed; no bun/yarn/pnpm lockfiles

### Assets

**Icon**
([guide](https://developers.raycast.com/basics/prepare-an-extension-for-store#extension-icon),
[Icon Maker](https://icon.ray.so/))

- 512×512 PNG in `assets/`; readable on light and dark UI; not default Raycast icon

**Screenshots** ([specs](https://developers.raycast.com/basics/prepare-an-extension-for-store#screenshots))

- `metadata/{extension-name}-{N}.png`, 2000×1250 PNG, max 6 (≥3 recommended)
- Window Capture + **Save to Metadata** in dev mode; one theme; no sensitive data

### Docs

- `CHANGELOG.md`: top entry uses `{PR_MERGE_DATE}`; accurate features only
- `README.md`: required if setup needed; README media in `media/`, not `metadata/`

## Contributing to extensions you don't own

Add yourself to `contributors` in `package.json`; update `CHANGELOG.md`.
