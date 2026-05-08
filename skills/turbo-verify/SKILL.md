---
name: turbo-verify
description:
  Verify that a theme implementation is complete and follows all project standards. Use
  after adding a new theme to turbo-themes.
---

# Verify Theme Implementation

Use this skill to verify that a theme implementation is complete and follows all
turbo-themes standards.

## Usage

When asked to verify a theme (e.g., `/turbo-verify rose-pine`), run through all
checklist items below.

---

## 1. Core Implementation

### Theme Pack Definition

- [ ] `src/themes/packs/<theme>.synced.ts` or `<theme>.ts` exists
- [ ] Exports a `ThemePackage` object with:
  - `id` - theme family identifier (lowercase)
  - `name` - display name
  - `homepage` - theme homepage URL
  - `license` - (recommended) license metadata with `spdx`, `url`, `copyright`
  - `source` - (recommended for synced) source metadata with `package`, `version`, `repository`
  - `flavors` - array of theme variants
- [ ] Each flavor has:
  - `id` - unique identifier (lowercase with hyphens)
  - `label` - full display name (e.g., "Catppuccin Mocha", "Gruvbox Dark Hard", "Solarized Light")
  - `vendor` - matches theme family
  - `appearance` - 'light' or 'dark'
  - `tokens` - complete token object with all required groups
- [ ] No `iconUrl` in flavor definitions (icons resolved via `VENDOR_ICON_MAP` in theme-mapper.ts)

### Required Token Groups

- [ ] `background` - base, surface, overlay
- [ ] `text` - primary, secondary, inverse
- [ ] `brand` - primary
- [ ] `state` - info, success, warning, danger
- [ ] `border` - default
- [ ] `accent` - link
- [ ] `typography` - fonts (sans, mono), webFonts
- [ ] `content` - heading (h1-h6), body, link, selection, blockquote, codeInline,
      codeBlock, table

### Theme Registry

- [ ] Theme imported in `src/themes/registry.ts`
- [ ] Theme flavors spread into `allFlavors` array

### W3C Design Token Files

- [ ] JSON file exists for each variant in
      `schema/tokens/themes/<variant-id>.tokens.json`
- [ ] Files use W3C Design Tokens format (`$value`, `$type`)
- [ ] `$schema` points to `../../turbo-themes.schema.json#/$defs/ThemeFile`

### Theme Icons

- [ ] PNG icon exists for each variant in `assets/img/<variant-id>.png`
- [ ] Icons are appropriately sized (typically 24x24)

---

## 2. Theme Selector Package

### Types (`packages/theme-selector/src/types.ts`)

- [ ] Theme family added to `ThemeFamily` type union

### Constants (`packages/theme-selector/src/constants.ts`)

- [ ] Theme added to `THEME_FAMILIES` with:
  - `name` - display name
  - `description` - short description

### Theme Mapper (`packages/theme-selector/src/theme-mapper.ts`)

- [ ] Theme added to `VENDOR_FAMILY_MAP`
- [ ] Theme added to `VENDOR_ICON_MAP` (string or AppearanceIcons object)
- [ ] Optionally: descriptions added to `FLAVOR_DESCRIPTIONS`

---

## 3. Site Integration

### Theme Metadata (`apps/site/src/data/theme-meta.ts`)

This is the **single source of truth** for the site. Both `ThemeDropdown.astro`
and `BaseLayout.astro` are data-driven from this file.

- [ ] Theme group added to `themeGroups` array with `id`, `displayName`, and `flavors`
- [ ] All variants added to `themeNames` with short display labels (e.g., "Mocha", "Dark Hard" — shorter than the token `label` field)
- [ ] All variants added to `themeIcons` with icon filenames
- [ ] `validThemeIds` is auto-derived (verify count matches expected total)

### Theme Dropdown (`apps/site/src/components/ThemeDropdown.astro`)

- [ ] Imports from `theme-meta.ts` (data-driven, no hardcoded theme buttons)
- [ ] Theme appears in dropdown under correct group when rendered

### Theme Explorer (`apps/site/src/pages/themes.astro`)

- [ ] Theme family added to sidebar with:
  - Family header with icon, name, and count
  - Button for each variant with color dot
- [ ] Theme variants added to JavaScript `themeNames` object

### Base Layout (`apps/site/src/layouts/BaseLayout.astro`)

- [ ] Imports `validThemeIds` from `theme-meta.ts` (data-driven, no hardcoded VALID_THEMES)
- [ ] Uses `define:vars` to pass `validThemeIds` to inline script

### Index Page (`apps/site/src/pages/index.astro`)

- [ ] Theme added to hero preview strip buttons (alongside Bulma, Catppuccin, etc.)

---

## 4. Build Verification

Run these commands and verify success:

```bash
# Linting passes (run first for fast failure)
uv run lintro chk
# Expected: 0 issues

# Core build passes
bun run build
# Expected: "Build complete!" with theme count including new themes

# Example projects build
bun run examples:build
# Expected: All example projects (react, vue, bootstrap, tailwind) build successfully

# Unit tests pass
bun run test
# Expected: All tests pass (no failures)

# Example E2E tests pass
bun run examples:test
# Expected: All example E2E tests pass

# Site builds
cd apps/site && bun run build
# Expected: No errors
```

**Note on Visual Regression Tests**: If E2E visual regression tests fail after adding themes
to the hero preview strip, this is expected. Visual snapshots are generated on Linux CI.
Use the `maintenance-generate-snapshots.yml` workflow to regenerate them:
Actions → Maintenance: Generate Playwright Snapshots → Run workflow

---

## 4.5 Build Pipeline Verification

### Sync Script Integration (if using sync script)

- [ ] Sync script added to `theme:sync` in package.json
- [ ] Sync script output path is `src/themes/packs/` (NOT `packages/core/src/themes/packs/`)
- [ ] Sync script reads version from `node_modules/<package>/package.json`
- [ ] `source.version` field is populated in generated ThemePackage
- [ ] Build succeeds from clean state (test: delete `.synced.ts` file and run build)
- [ ] Generated `.synced.ts` file is created during build

### Style Dictionary Metadata (`scripts/prepare-style-dictionary.mjs`)

- [ ] Theme added to `vendorMeta` object with correct `name` and `homepage`
- [ ] Generated `tokens.json` files show correct metadata for theme

### Generated Assets

After all changes, verify these files are committed:

- [ ] `assets/js/theme-selector.js` - bundled with new theme support
- [ ] `assets/js/theme-selector.js.map`
- [ ] `assets/js/theme-selector.min.js`
- [ ] `packages/core/src/themes/tokens.json`
- [ ] `python/src/turbo_themes/tokens.json`
- [ ] `swift/Sources/TurboThemes/Resources/tokens.json`

### Flavor Descriptions

- [ ] All variants have entries in `FLAVOR_DESCRIPTIONS` in theme-mapper.ts

---

## 4.6 Example Files Verification

### Web Examples (hardcoded theme lists)

- [ ] `examples/html-vanilla/index.html` - `<select>` options and `VALID_THEMES` array
- [ ] `examples/bootstrap/index.html` - `<select>`, `VALID_THEMES`, and `lightThemes`
- [ ] `examples/react/index.html` - `VALID_THEMES` in FOUC script
- [ ] `examples/vue/index.html` - `VALID_THEMES` in FOUC script
- [ ] `examples/tailwind/index.html` - `<select>` options and `VALID_THEMES` array
- [ ] `examples/jekyll/_layouts/default.html` - `<select>`, FOUC `VALID_THEMES`, main `VALID_THEMES`
- [ ] `examples/stackblitz/html-vanilla/index.html` - `<select>` and `VALID_THEMES`
- [ ] `examples/stackblitz/bootstrap/index.html` - `<select>` options
- [ ] `examples/stackblitz/bootstrap/src/main.js` - `VALID_THEMES` and `LIGHT_THEMES`
- [ ] `examples/stackblitz/tailwind/index.html` - `<select>` options
- [ ] `examples/stackblitz/tailwind/src/main.js` - `VALID_THEMES`
- [ ] `examples/stackblitz/react/src/App.tsx` - `THEMES` array
- [ ] `examples/stackblitz/vue/src/App.vue` - `THEMES` array

**Note:** These files auto-update from core and do NOT need manual changes:
- `examples/react/src/hooks/useTheme.ts`
- `examples/vue/src/composables/useTheme.ts`
- `examples/bootstrap/src/main.ts`

### Swift Example (`examples/swift-swiftui/`)

- [ ] `Sources/TurboThemes/ThemeId.swift` - enum cases for all variants
- [ ] `Sources/TurboThemes/ThemeRegistry.swift` - `ThemeDefinition` with palette for each variant
- [ ] `Tests/.../ThemeRegistryTests.swift` - expected count matches total themes
- [ ] `Tests/.../ThemeRegistryTests.swift` - `expectedLabels` includes all variants
- [ ] `Tests/.../ThemeRegistryTests.swift` - `testThemeIdRawValues` includes all variants

---

## 5. Functional Testing

### Theme Selection

- [ ] Theme appears in header dropdown under correct family group
- [ ] Selecting theme updates page styling correctly
- [ ] Header shows correct icon when theme selected
- [ ] Header shows correct short label when theme selected (not ID or full name)

### Theme Persistence

- [ ] Selected theme persists after page refresh
- [ ] Selected theme persists when navigating to other pages
- [ ] Theme doesn't revert to default unexpectedly

### Theme Explorer Page

- [ ] Theme family appears in sidebar
- [ ] All variants selectable
- [ ] Color palette displays correctly for each variant
- [ ] Live preview updates when variant selected

### CSS Generation

- [ ] CSS file generated for each variant in build output
- [ ] CSS variables set correctly when theme applied

---

## 6. Common Issues Checklist

- [ ] **No "theme reverts" bug**: Variants in `VALID_THEMES` (BaseLayout.astro)
- [ ] **Correct label in header**: Variants in `themeNames` (BaseLayout.astro)
- [ ] **Icon displays**: Variants in `themeIcons` (BaseLayout.astro) and files exist
- [ ] **In correct dropdown group**: `VENDOR_FAMILY_MAP` mapping correct
- [ ] **Theme count accurate**: Count in themes.astro sidebar matches variants
- [ ] **Tests not broken**: Any hardcoded theme arrays in tests updated
- [ ] **Examples updated**: All hardcoded theme lists in `examples/` include new variants
- [ ] **Swift example updated**: ThemeId enum, ThemeRegistry, and tests updated

---

## 7. Verification Commands

```bash
# Check theme appears in build summary
bun run build 2>&1 | grep "Total themes"

# Check CSS files generated
ls -la dist/themes/<theme>*.css

# Check icons exist
ls -la assets/img/<theme>*.png

# Check JSON token files
ls -la schema/tokens/themes/<theme>*.tokens.json

# Check theme-selector package exports theme family
grep "<theme>" packages/theme-selector/src/types.ts
grep "<theme>" packages/theme-selector/src/constants.ts
grep "<theme>" packages/theme-selector/src/theme-mapper.ts

# Check site integration
grep "<theme>" apps/site/src/components/ThemeDropdown.astro
grep "<theme>" apps/site/src/pages/themes.astro
grep "<theme>" apps/site/src/layouts/BaseLayout.astro

# Check vendorMeta in prepare-style-dictionary.mjs
grep "<theme>" scripts/prepare-style-dictionary.mjs

# Check theme:sync includes the sync script (if applicable)
grep "sync-<theme>" package.json

# Verify build works from clean state (if using sync script)
rm -f src/themes/packs/<theme>.synced.ts && bun run build

# Check FLAVOR_DESCRIPTIONS
grep "<theme>" packages/theme-selector/src/theme-mapper.ts | grep -i description

# Check license/source metadata in theme pack
grep -A3 "license:" src/themes/packs/<theme>.ts
grep -A4 "source:" src/themes/packs/<theme>.ts

# Verify sync script output path (should be src/themes/packs/, not packages/core/...)
grep "outPath" scripts/sync-<theme>.mjs

# Check hero preview strip
grep "<theme>" apps/site/src/pages/index.astro | grep "button"

# Check theme-meta.ts (single source of truth for site)
grep "<theme>" apps/site/src/data/theme-meta.ts

# Check example files have the theme
grep "<theme>" examples/html-vanilla/index.html
grep "<theme>" examples/bootstrap/index.html
grep "<theme>" examples/react/index.html
grep "<theme>" examples/tailwind/index.html
grep "<theme>" examples/jekyll/_layouts/default.html
grep "<theme>" examples/stackblitz/html-vanilla/index.html
grep "<theme>" examples/stackblitz/bootstrap/index.html
grep "<theme>" examples/stackblitz/bootstrap/src/main.js
grep "<theme>" examples/stackblitz/tailwind/index.html
grep "<theme>" examples/stackblitz/tailwind/src/main.js
grep "<theme>" examples/stackblitz/react/src/App.tsx
grep "<theme>" examples/stackblitz/vue/src/App.vue

# Check Swift example
grep "<theme>" examples/swift-swiftui/Sources/TurboThemes/ThemeId.swift
grep "<theme>" examples/swift-swiftui/Sources/TurboThemes/ThemeRegistry.swift
grep "<theme>" examples/swift-swiftui/Tests/TurboThemesTests/ThemeRegistryTests.swift
```

---

## Review Output Format

After reviewing, provide a summary:

```
## Theme Review: <theme_name>

### Status: PASS / FAIL / PARTIAL

### Checklist Summary
- Core Implementation: X/Y items
- Theme Selector Package: X/Y items
- Site Integration: X/Y items
- Build Verification: X/Y items
- Functional Testing: X/Y items

### Missing Items
1. [item description]
2. [item description]

### Recommendations
1. [recommendation]
2. [recommendation]
```

---

## Quick Fix Reference

| Issue                       | Solution                                          |
| --------------------------- | ------------------------------------------------- |
| Theme reverts on navigation | Add to `VALID_THEMES` in BaseLayout.astro         |
| Wrong/missing label         | Add to `themeNames` in BaseLayout.astro           |
| Missing icon                | Add to `themeIcons` in BaseLayout.astro + add PNG |
| Theme in wrong group        | Fix `VENDOR_FAMILY_MAP` in theme-mapper.ts        |
| Theme not appearing         | Check ThemeFamily type, THEME_FAMILIES constant   |
| Build fails                 | Check TypeScript syntax, imports                  |
| Tests fail                  | Update assertions to use `data-theme-id` lookups  |
| Bundle too large            | Increase budget in bundle-size.test.ts            |
| CI "Cannot find module"     | Add sync script to `theme:sync` in package.json   |
| tokens.json wrong metadata  | Add to `vendorMeta` in prepare-style-dictionary.mjs |
| Generated assets outdated   | Run `bun run build` and commit generated files    |
| Missing descriptions        | Add to `FLAVOR_DESCRIPTIONS` in theme-mapper.ts   |
| Missing license/source      | Add `license` and `source` to ThemePackage        |
| Sync writes to wrong path   | Change outPath to `src/themes/packs/`             |
| Missing version in source   | Read from `node_modules/<pkg>/package.json`       |
| Visual regression fails     | Run `maintenance-generate-snapshots.yml` workflow |
| Missing from hero strip     | Add buttons to index.astro hero preview section   |
| Missing from examples       | Update ~16 example files with hardcoded theme lists |
| Missing from Swift example  | Add to ThemeId.swift, ThemeRegistry.swift, tests  |
| Theme not in site dropdown  | Add to `themeGroups` in theme-meta.ts             |
| Wrong label in site header  | Fix `themeNames` in theme-meta.ts                 |
| Missing icon in site header | Fix `themeIcons` in theme-meta.ts + add PNG       |
