---
name: design
description: >-
  Create distinctive, production-grade frontend interfaces with high design quality.
  Use this skill when the user asks to build web components, pages, artifacts,
  posters, or applications (examples include websites, landing pages, dashboards,
  React components, HTML/CSS layouts, or when styling/beautifying any web UI).
  Generates creative, polished code and UI design that avoids generic AI aesthetics.
license: Complete terms in LICENSE.txt
upstream:
  repo: anthropics/claude-code
  path: plugins/frontend-design/skills/frontend-design/SKILL.md
  version: "1.1.0"
---

# Design

This skill guides creation of distinctive, production-grade frontend interfaces that
avoid generic "AI slop" aesthetics. Implement real working code with exceptional
attention to aesthetic details and creative choices.

The user provides frontend requirements: a component, page, application, or
interface to build. They may include context about the purpose, audience, or
technical constraints.

## Design Thinking

Before coding, understand the context and commit to a bold aesthetic direction:

- **Purpose**: What problem does this interface solve? Who uses it?
- **Tone**: Pick an extreme: brutally minimal, maximalist chaos, retro-futuristic,
  organic/natural, luxury/refined, playful/toy-like, editorial/magazine,
  brutalist/raw, art deco/geometric, soft/pastel, industrial/utilitarian, etc.
- **Constraints**: Technical requirements (framework, performance, accessibility).
- **Differentiation**: What makes this memorable? What's the one thing someone will
  remember?

Choose a clear conceptual direction and execute it with precision. Bold maximalism and
refined minimalism both work—the key is intentionality, not intensity. Match
implementation complexity to the vision: maximalist designs need elaborate animation
and effects; minimalist designs need restraint, spacing, and typography precision.

## Frontend Aesthetics Guidelines

Focus on:

- **Typography**: Choose fonts that are beautiful, unique, and interesting. Avoid
  generic fonts like Arial and Inter; opt instead for distinctive choices that
  elevate the frontend's aesthetics. Pair a distinctive display font with a refined
  body font.
- **Color & Theme**: Commit to a cohesive aesthetic. Use CSS variables for
  consistency. Dominant colors with sharp accents outperform timid,
  evenly-distributed palettes.
- **Motion**: Use animations for effects and micro-interactions. Prioritize CSS-only
  solutions for HTML. Use Motion library for React when available. Focus on
  high-impact moments: one well-orchestrated page load with staggered reveals
  (animation-delay) creates more delight than scattered micro-interactions.
- **Spatial Composition**: Unexpected layouts. Asymmetry. Overlap. Diagonal flow.
  Grid-breaking elements. Generous negative space OR controlled density.
- **Backgrounds & Visual Details**: Create atmosphere and depth rather than
  defaulting to solid colors. Add contextual effects and textures that match the
  overall aesthetic—gradient meshes, noise textures, geometric patterns, layered
  transparencies, dramatic shadows, decorative borders, and grain overlays.

NEVER use generic AI-generated aesthetics like overused font families (Inter, Roboto,
Arial, system fonts), cliched color schemes (particularly purple gradients on white
backgrounds), predictable layouts and component patterns, and cookie-cutter design
that lacks context-specific character.

Interpret creatively and make unexpected choices that feel genuinely designed for
the context. Vary between light and dark themes, different fonts, and different
aesthetics. NEVER converge on common choices (Space Grotesk, for example) across
generations.

## Accessibility (Non-negotiable)

Every component must include:

- Semantic HTML elements (`<nav>`, `<main>`, `<article>`, not `<div>` soup)
- `aria-label` on interactive elements without visible text (icon-only buttons, etc.)
- Color contrast ratio >= 4.5:1 for body text, >= 3:1 for large text (WCAG AA)
- Keyboard navigation support: use `tabindex="0"` for focusable elements in natural tab
  order; use `tabindex="-1"` only when programmatic focus is needed (e.g., modal traps).
  Never use positive `tabindex` values—they break predictable focus order (WCAG 2.4.3).
  Always pair with visible focus styles and avoid mouse-only interactions.
- `prefers-reduced-motion` media query wrapping all animations
- `alt` text on all images; decorative images use `alt=""`

## Component Structure

- Use CSS custom properties (`--color-primary`, `--spacing-md`) for all design tokens
- Font imports via `<link>` or `@import` — never inline `font-family` without a
  variable
- Responsive breakpoints: mobile-first, minimum 3 breakpoints (sm: 640px, md: 768px,
  lg: 1024px)
- No inline styles except for dynamic values (e.g., `style={{ '--progress': value }}`)
- All spacing via a consistent scale (4px base or 8px base — pick one and use it)

## Before Submitting

1. Run through an accessibility audit: `npx @axe-core/cli <url>` or manual check
   against the list above
2. Test at 640px, 768px, and 1024px viewport widths (matching sm/md/lg breakpoints);
   optionally add 320px for mobile minimum
3. Verify no hardcoded color values outside CSS variables
4. Confirm `prefers-reduced-motion` is respected
5. Verify font loading: each `@font-face` sets `font-display: swap` (or another
   explicit value); pages define a fallback stack ending with a generic family (e.g.,
   `system-ui, Helvetica, Arial, sans-serif`). Under 3G throttling, computed
   `font-family` must be a fallback within 1s and the webfont must replace it within
   5s. Test manually (DevTools network throttling) or with automation (e.g., Puppeteer
   asserting computed `font-family` and timing) to confirm no prolonged invisible text
   (FOIT)
