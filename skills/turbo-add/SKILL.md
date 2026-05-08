---
name: turbo-add
description:
  Guide for adding a new theme family to turbo-themes. Use when implementing Nord,
  Solarized, Gruvbox, Tokyo Night, One Dark, Ayu, Kanagawa, Everforest, Radix, or any
  new theme.
---

# Adding a New Theme to Turbo-Themes

This document serves as a comprehensive guide for adding a new theme family to
turbo-themes.

## Related Skills

- **stand-ts**: Follow TypeScript coding standards
- **commit**: Use semantic commit format when committing changes
- **turbo-verify**: Use after implementation to verify completeness

## Quick Reference

### Files to Create

```
scripts/sync-<theme>.mjs                           # Optional: sync from npm package
src/themes/packs/<theme>.synced.ts                 # Theme definitions
schema/tokens/themes/<theme-id>.tokens.json        # W3C Design Token files (one per variant)
assets/img/<theme-id>.png                          # Theme icons (one per variant)
```

### Files to Update

```
src/themes/registry.ts                             # Import and register themes
packages/theme-selector/src/types.ts               # Add to ThemeFamily type
packages/theme-selector/src/constants.ts           # Add to THEME_FAMILIES
packages/theme-selector/src/theme-mapper.ts        # Add to VENDOR_FAMILY_MAP, VENDOR_ICON_MAP
apps/site/src/data/theme-meta.ts                   # Add to themeGroups, themeNames, themeIcons (single source of truth)
apps/site/src/pages/themes.astro                   # Add to theme explorer
apps/site/src/pages/index.astro                    # Add to hero preview strip
test/integration/bundle-size.test.ts               # May need to increase budget
scripts/prepare-style-dictionary.mjs               # Add to vendorMeta
```

### Example Files to Update

```
examples/html-vanilla/index.html                   # <select> options + VALID_THEMES array
examples/bootstrap/index.html                      # <select> options + VALID_THEMES + lightThemes
examples/react/index.html                          # VALID_THEMES in FOUC script
examples/vue/index.html                            # VALID_THEMES in FOUC script
examples/tailwind/index.html                       # <select> options + VALID_THEMES array
examples/jekyll/_layouts/default.html              # <select> options + VALID_THEMES (FOUC + main script)
examples/stackblitz/html-vanilla/index.html        # <select> options + VALID_THEMES array
examples/stackblitz/bootstrap/index.html           # <select> options
examples/stackblitz/bootstrap/src/main.js          # VALID_THEMES + LIGHT_THEMES arrays
examples/stackblitz/tailwind/index.html            # <select> options
examples/stackblitz/tailwind/src/main.js           # VALID_THEMES array
examples/stackblitz/react/src/App.tsx              # THEMES array
examples/stackblitz/vue/src/App.vue                # THEMES array
examples/swift-swiftui/Sources/TurboThemes/ThemeId.swift         # Add enum cases
examples/swift-swiftui/Sources/TurboThemes/ThemeRegistry.swift   # Add ThemeDefinition entries
examples/swift-swiftui/Tests/.../ThemeRegistryTests.swift        # Update counts + labels
```

**Note:** Some example files are dynamic and auto-update from core:
- `examples/react/src/hooks/useTheme.ts` (imports from `@lgtm-hq/turbo-themes-core/tokens`)
- `examples/vue/src/composables/useTheme.ts` (imports from `@lgtm-hq/turbo-themes-core/tokens`)
- `examples/bootstrap/src/main.ts` (imports from `@lgtm-hq/turbo-themes-core/tokens`)

---

## Project Context

Turbo-themes uses a token-based theming system:

1. Theme definitions in `src/themes/packs/<theme>.ts` define colors/tokens
2. The registry in `src/themes/registry.ts` collects all themes
3. Build generates CSS files from tokens
4. Theme-selector package provides UI components
5. Site displays themes with hardcoded dropdown/explorer options

---

## Files to Create

### 1. Theme Pack Definition (`src/themes/packs/<theme>.synced.ts`)

```typescript
import type { ThemePackage } from '../types.js';

export const <theme>Synced: ThemePackage = {
  id: '<theme>',
  name: '<Theme Name> (synced)',
  homepage: 'https://<theme-homepage>',
  license: {
    spdx: 'MIT',  // Use SPDX identifier (MIT, Apache-2.0, CC-BY-SA-4.0, etc.)
    url: 'https://github.com/<org>/<repo>/blob/main/LICENSE',
    copyright: '<Copyright Holder>',
  },
  source: {
    package: '@<org>/palette',  // npm package name if synced
    version: '1.0.0',           // Read from node_modules at sync time
    repository: 'https://github.com/<org>/<repo>',
  },
  flavors: [
    {
      id: '<theme-variant>',
      label: '<Theme Variant Full Name>',  // Full display name (e.g., "Catppuccin Mocha", "Gruvbox Dark Hard")
      vendor: '<theme>',
      appearance: 'dark',  // or 'light'
      tokens: {
        background: {
          base: '#191724',
          surface: '#1f1d2e',
          overlay: '#26233a',
        },
        text: {
          primary: '#e0def4',
          secondary: '#908caa',
          inverse: '#191724',
        },
        brand: {
          primary: '#c4a7e7',
        },
        state: {
          info: '#9ccfd8',
          success: '#31748f',
          warning: '#f6c177',
          danger: '#eb6f92',
        },
        border: {
          default: '#403d52',
        },
        accent: {
          link: '#c4a7e7',
        },
        typography: {
          fonts: {
            sans: 'Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji"',
            mono: 'JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
          },
          webFonts: [
            'https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap',
            'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap',
          ],
        },
        content: {
          heading: {
            h1: '#31748f',
            h2: '#c4a7e7',
            h3: '#9ccfd8',
            h4: '#f6c177',
            h5: '#ebbcba',
            h6: '#eb6f92',
          },
          body: {
            primary: '#e0def4',
            secondary: '#908caa',
          },
          link: {
            default: '#c4a7e7',
          },
          selection: {
            fg: '#e0def4',
            bg: '#524f67',
          },
          blockquote: {
            border: '#524f67',
            fg: '#e0def4',
            bg: '#1f1d2e',
          },
          codeInline: {
            fg: '#e0def4',
            bg: '#26233a',
          },
          codeBlock: {
            fg: '#e0def4',
            bg: '#26233a',
          },
          table: {
            border: '#524f67',
            stripe: '#26233a',
            theadBg: '#403d52',
          },
        },
      },
    },
    // Add more variants here...
  ],
} as const;
```

### 2. W3C Design Token File (`schema/tokens/themes/<theme-id>.tokens.json`)

Create one file per variant following the W3C Design Tokens format:

```json
{
  "$schema": "../../turbo-themes.schema.json#/$defs/ThemeFile",
  "id": "<theme-variant>",
  "label": "<Theme Variant Full Name>",
  "vendor": "<theme>",
  "appearance": "dark",
  "tokens": {
    "background": {
      "base": { "$value": "#191724", "$type": "color" },
      "surface": { "$value": "#1f1d2e", "$type": "color" },
      "overlay": { "$value": "#26233a", "$type": "color" }
    }
    // ... same structure as TypeScript but with $value/$type format
  }
}
```

### 3. Theme Icons (`assets/img/<theme-id>.png`)

- Add PNG icons for each variant (typically 24x24 or similar)
- Icons should be visually distinct for light/dark variants

### 4. Sync Script (Optional: `scripts/sync-<theme>.mjs`)

If the theme has an npm package with palette data:

```javascript
#!/usr/bin/env node
/**
 * Sync <Theme> palette from @<theme>/palette npm package.
 * Run: node scripts/sync-<theme>.mjs
 */

import { writeFileSync } from 'fs';
import { palette } from '@<theme>/palette';

// Map palette colors to turbo-themes tokens
const variants = Object.entries(palette).map(([key, colors]) => ({
  id: `<theme>-${key}`,
  label: key.charAt(0).toUpperCase() + key.slice(1),
  vendor: '<theme>',
  appearance: colors.isLight ? 'light' : 'dark',
  // ... map colors to tokens
}));

// Generate TypeScript output
const output = `import type { ThemePackage } from '../types.js';

export const <theme>Synced: ThemePackage = {
  id: '<theme>',
  name: '<Theme> (synced)',
  homepage: 'https://<theme-homepage>',
  flavors: ${JSON.stringify(variants, null, 2)},
} as const;
`;

writeFileSync('src/themes/packs/<theme>.synced.ts', output);
console.log('Synced <theme> themes');
```

### Sync Script Best Practices

When writing a sync script:

1. **Output path must be `src/themes/packs/`** - The registry imports from `src/themes/packs/`,
   NOT `packages/core/src/themes/packs/`:

   ```javascript
   // CORRECT
   const outPath = path.join(projectRoot, 'src', 'themes', 'packs', '<theme>.synced.ts');

   // WRONG - registry won't find the file
   const outPath = path.join(projectRoot, 'packages', 'core', 'src', 'themes', 'packs', '<theme>.synced.ts');
   ```

2. **Read version from node_modules** - Include version metadata for traceability:

   ```javascript
   const packageJson = JSON.parse(
     fs.readFileSync(path.join(projectRoot, 'node_modules', '@<theme>', 'palette', 'package.json'), 'utf8')
   );
   const version = packageJson.version;

   // Use in output:
   source: {
     package: '@<theme>/palette',
     version: version,  // e.g., '1.7.1'
     repository: 'https://github.com/<org>/palette',
   },
   ```

3. **Normalize hex colors** - Source packages may include '#' prefix inconsistently:

   ```javascript
   function normalizeHex(color) {
     const hex = color.hex.replace(/^#/, '');
     return `#${hex}`;
   }
   ```

4. **Deterministic ordering** - Sort variant keys for reproducible builds:

   ```javascript
   const sortedKeys = Object.keys(variants).sort();
   for (const key of sortedKeys) {
     // Process variants in consistent order
   }
   ```

5. **Add to theme:sync** - Update package.json so the build pipeline generates the file

---

## Files to Update

### 1. Theme Registry (`src/themes/registry.ts`)

```typescript
import { <theme>Synced } from './packs/<theme>.synced.js';

const allFlavors: ThemeFlavor[] = [
  // ... existing themes ...
  ...<theme>Synced.flavors,
];
```

### 2. ThemeFamily Type (`packages/theme-selector/src/types.ts`)

```typescript
export type ThemeFamily =
  | 'bulma'
  | 'catppuccin'
  | 'github'
  | 'dracula'
  | 'rose-pine'
  | '<theme>';
```

### 3. Theme Families Metadata (`packages/theme-selector/src/constants.ts`)

```typescript
export const THEME_FAMILIES: Record<ThemeFamily, ThemeFamilyMeta> = {
  // ... existing ...
  '<theme>': { name: '<Theme Name>', description: '<Theme description>' },
};
```

### 4. Theme Mapper (`packages/theme-selector/src/theme-mapper.ts`)

```typescript
const VENDOR_FAMILY_MAP: Record<string, ThemeFamily> = {
  // ... existing ...
  '<theme>': '<theme>',
};

// VENDOR_ICON_MAP is the sole source for icon resolution.
// Do NOT add iconUrl to individual flavor definitions in theme packs or W3C token files.
const VENDOR_ICON_MAP: Record<string, string | AppearanceIcons> = {
  // ... existing ...
  '<theme>': 'assets/img/<theme>.png',
  // Or for appearance-specific icons (use when family has both light and dark variants):
  '<theme>': {
    light: 'assets/img/<theme>-light.png',
    dark: 'assets/img/<theme>-dark.png',
  },
};

// Add descriptions for each variant
const FLAVOR_DESCRIPTIONS: Partial<Record<string, string>> = {
  // ... existing ...
  '<theme-variant-1>': 'Description of this variant.',
  '<theme-variant-2>': 'Deeper variant with enhanced contrast.',
  '<theme-light>': 'Light variant for daytime use.',
};
```

### 5. Site Theme Metadata (`apps/site/src/data/theme-meta.ts`)

This is the **single source of truth** for the site's theme dropdown, VALID_THEMES,
and icon/label mappings. Both `BaseLayout.astro` and `ThemeDropdown.astro` are data-driven
from this file.

```typescript
// Add to themeGroups array (ordered by display position)
export const themeGroups: ThemeGroup[] = [
  // ... existing groups ...
  {
    id: '<theme>',
    displayName: '<Theme Name>',
    flavors: ['<theme-variant-1>', '<theme-variant-2>'],
  },
];

// Add to themeNames (short labels for dropdown trigger)
export const themeNames: Record<string, string> = {
  // ... existing ...
  '<theme-variant-1>': '<Short Label>',
  '<theme-variant-2>': '<Short Label>',
};

// Add to themeIcons (icon filenames relative to /assets/img/)
export const themeIcons: Record<string, string> = {
  // ... existing ...
  '<theme-variant-1>': '<theme-variant-1>.png',
  '<theme-variant-2>': '<theme-variant-2>.png',
};
```

**Important:** `validThemeIds` is derived automatically via `themeGroups.flatMap(g => g.flavors)`.
`ThemeDropdown.astro` and `BaseLayout.astro` both import from this file - no hardcoded
arrays to maintain.

### 6. Site Theme Explorer (`apps/site/src/pages/themes.astro`)

Add to sidebar and themeNames JavaScript object:

```astro
<!-- Sidebar -->
<div class="theme-family">
  <button class="family-header" aria-expanded="true">
    <span class="family-label">
      <img class="family-icon" src={`${baseUrl}/assets/img/<theme>.png`} alt="" width="24" height="24" />
      <span class="family-name"><Theme Name></span>
    </span>
    <span class="family-count">N</span>
  </button>
  <div class="family-themes">
    <button class="theme-option" data-theme="<theme-variant>">
      <span class="theme-dot" style="background: #<base-color>"></span>
      <Variant Label>
    </button>
  </div>
</div>

<!-- JavaScript themeNames -->
var themeNames = {
  // ... existing ...
  '<theme-variant>': { name: '<Theme Variant>', mode: 'Dark' },
};
```

### 7. Site Base Layout & Index Page

`BaseLayout.astro` and `ThemeDropdown.astro` are now **data-driven** from
`apps/site/src/data/theme-meta.ts`. No direct edits needed for these files if
you updated `theme-meta.ts` correctly (step 5 above).

`apps/site/src/pages/index.astro` still has a hero preview strip - add theme buttons
for the new theme alongside existing ones.

### 8. Bundle Size Test (if needed)

If the bundle size increases significantly:

```typescript
// test/integration/bundle-size.test.ts
const BUNDLE_SIZE_BUDGET = 55 * 1024; // Increase if needed
```

### 9. Style Dictionary Metadata (`scripts/prepare-style-dictionary.mjs`)

Add to `vendorMeta`:

```javascript
const vendorMeta = {
  // ... existing ...
  '<theme>': { name: '<Theme Name>', homepage: 'https://<theme-homepage>/' },
};
```

### 10. Package.json (if using sync script)

Add sync script to `theme:sync`:

```json
"theme:sync": "node scripts/sync-catppuccin.mjs && node scripts/sync-<theme>.mjs"
```

### 11. Example Files

Add the new theme variants to all example projects with hardcoded theme lists.
Each file has different areas to update (dropdowns, VALID_THEMES arrays, LIGHT_THEMES arrays).

**Web examples** need theme IDs added to:
- `<select>` dropdown `<option>` elements
- `VALID_THEMES` JavaScript arrays (FOUC scripts and main scripts)
- `LIGHT_THEMES` arrays (if present, add light variants)
- `THEMES` arrays in React/Vue components (id + display name)

**Swift example** (`examples/swift-swiftui/`) needs:
- New enum cases in `ThemeId.swift`
- Full `ThemeDefinition` entries with color palettes in `ThemeRegistry.swift`
- Updated counts and labels in `ThemeRegistryTests.swift`

**Tip:** Some web examples import from `@lgtm-hq/turbo-themes-core/tokens` and
auto-update (React hooks, Vue composables, Bootstrap main.ts). Only update files
with hardcoded theme lists.

---

## Naming Conventions

- **Theme ID**: lowercase with hyphens (e.g., `rose-pine-moon`)
- **Variant Label** (token `label` field): Full display name including theme family
  (e.g., "Catppuccin Mocha", "Gruvbox Dark Hard", "Solarized Light", "Rosé Pine Moon")
  - Match the convention in W3C `.tokens.json` files and existing theme packs
- **Short Label** (site `themeNames` in `theme-meta.ts`): Short name for dropdown trigger
  (e.g., "Mocha", "Dark Hard", "Light", "Moon")
  - These are the condensed labels shown in the site header when a theme is selected
- **Vendor**: Same as theme family name (e.g., `rose-pine`)
- **Family**: Theme family identifier (e.g., `rose-pine`)

---

## Build and Test

After making changes:

```bash
# Lint
uv run lintro chk

# Build everything
bun run build
bun run examples:build

# Run all tests
bun run test
bun run examples:test

# Build the site
cd apps/site && bun run build

# Run the dev server to visually test
cd apps/site && bun run dev
```

**Tip:** Use `/turbo-test` to run the full pipeline automatically.

---

## Common Gotchas

1. **Theme reverts on page navigation**: Forgot to add variants to `VALID_THEMES` in
   BaseLayout.astro
2. **Wrong label in header**: Forgot to add to `themeNames` mapping in BaseLayout.astro
3. **No icon showing**: Forgot to add to `themeIcons` mapping or icon file missing
4. **Theme not in dropdown**: Forgot to add to `VENDOR_FAMILY_MAP` in theme-mapper.ts
5. **Theme in wrong family group**: `VENDOR_FAMILY_MAP` mapping is incorrect
6. **Tests fail with theme order**: Update test assertions to use `data-theme-id` attribute
   lookups instead of array indices
7. **Bundle size test fails**: Increase budget in bundle-size.test.ts
8. **CI fails "Cannot find module './packs/<theme>.synced.js'"**: Forgot to add sync script
   to `theme:sync` in package.json - the build pipeline must generate the file before
   TypeScript compilation
9. **tokens.json shows wrong name/homepage**: Forgot to add theme to `vendorMeta` in
   scripts/prepare-style-dictionary.mjs
10. **Generated assets outdated**: After changes, run `bun run build` and commit the
    generated files (`assets/js/theme-selector.*`, `tokens.json` files in core/python/swift)
11. **TypeScript build error with license/source fields**: If adding new interfaces to types,
    update BOTH `src/themes/types.ts` AND `packages/core/src/themes/types.ts` - they are
    separate files that must be kept in sync
12. **Visual regression tests fail after adding theme to hero**: E2E visual snapshots are
    generated on Linux CI. Use the `maintenance-generate-snapshots.yml` workflow to regenerate
    them (Actions → Maintenance: Generate Playwright Snapshots → Run workflow)
13. **Missing from hero preview strip**: Add theme buttons to `apps/site/src/pages/index.astro`
    in the hero theme preview area (alongside Bulma, Catppuccin, etc.)
14. **Missing from example files**: ~16 example files have hardcoded theme lists that
    need updating (dropdowns, VALID_THEMES, LIGHT_THEMES, THEMES arrays)
15. **Missing from Swift example**: `ThemeId.swift` enum, `ThemeRegistry.swift` palettes,
    and `ThemeRegistryTests.swift` counts/labels all need updating

---

## Reference Examples

See existing theme implementations:

- **Synced theme with npm package**: `src/themes/packs/catppuccin.synced.ts`,
  `scripts/sync-catppuccin.mjs`
- **Synced theme**: `src/themes/packs/rose-pine.synced.ts`
- **Manual theme with license/source metadata**: `src/themes/packs/nord.ts`
- **Manual theme**: `src/themes/packs/bulma.ts`, `src/themes/packs/dracula.ts`
