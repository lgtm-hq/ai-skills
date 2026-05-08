---
name: dashboard-redesign
description: Dashboard Redesign — Design vision and implementation guide for the Flowscout SPA dashboard. Use when working on the dashboard restructure, to reload the agreed-upon design direction, tab structure, and remaining tasks.
---

# Dashboard Redesign — Design Vision & Implementation Guide

Invoke `/dashboard-redesign` to reload context in any session.

## Goal

The dashboard serves two audiences:
1. **POM users** — want page object models for traditional UI testing
2. **MBT users** — want graph models for GraphWalker/AltWalker

The redesign ensures both deliverables are first-class citizens with clear
separation between crawl output (what exists now) and MBT test output (future).

## Architecture: Two-Tier Navigation

Replace the current horizontal-only tab bar with a **vertical sidebar** (left)
for top-level sections + **horizontal tabs** (top) within each section.

```
+----------------+-------------------------------------------+
|                |  Overview | Pages | Flows                  |
|  Exploration   |--------------------------------------------|
|                |                                            |
|                |  [content for selected horizontal tab]     |
|----------------|                                            |
|                |                                            |
|  Testing       |                                            |
|  (coming soon) |                                            |
|                |                                            |
+----------------+-------------------------------------------+
```

### Left Sidebar Sections

**Exploration** (populated now — all crawl data):
- Overview
- Pages
- Flows

**Testing** (future — MBT execution):
- Models (exported GraphWalker/AltWalker models)
- Test Runs (MBT execution results)
- Coverage (model coverage from test runs)
- Shows empty state placeholder until MBT is implemented

### Why Vertical Sidebar
- Scales better than horizontal tabs as sections grow
- Clearly separates "what was found" (crawl) from "what was tested" (MBT)
- Room for future sections (cross-run history, settings, export)

## Horizontal Tabs Within "Exploration"

### Overview Tab
What's currently the Summary tab, minus the Pages Discovered table:
- Exploration Report header (hostname, duration, stats)
- Exploration Efficiency section (stat cards with tooltips, progress bar)
- Issues modal (click Issues Found stat to review)
- Attention Required section
- Cross-Run Changes section

### Pages Tab
**The POM deliverable hub.** Discovery + page objects unified.

Content:
- **Pages Discovered table** (moved from Overview)
  - Grouped by URL, expandable to show individual states
  - "States" column with count, expand chevron for multi-state URLs
  - Uses `state_to_page_type` mapping for correct archetype/quality lookup
  - Archetype badges are clickable, opening the page object detail
- **Page Object cards** for each unique page type
  - Name, archetype, URL pattern
  - Locator table with quality scores
  - Code preview (POM class)
  - Recommendations for improving locators
  - Quality score with tone indicator
- Quality metrics that belong to pages:
  - Locator health rows
  - Locator recommendations

### Flows Tab
**The MBT deliverable hub.** Flows + graph + execution unified.

Sub-navigation pills: **Flows** | **Site Graph** | **All Steps**

**Flows pill** (default):
- Flow template cards with Gherkin-style rendering
- Page badges showing pages traversed per flow
- Expandable execution steps per flow
- Smart grouping when 10+ templates exist
- Stability badges per template

**Site Graph pill**:
- The existing GraphView component (full site graph, not per-flow)
- Page types as nodes, transitions as edges
- Future: click a flow template to highlight its path on the graph
- Coverage overlay (uncovered edges)

**All Steps pill**:
- Flat execution timeline for power users
- Step detail modal with title stripping

Quality metrics that belong to flows:
- Flaky actions
- Low stability steps

## Key Design Decisions

1. **Pages and page objects are the same entity** viewed from two angles
   (discovery vs artifact). They must live together, not in separate tabs.

2. **Quality tab is dissolved.** Locator health goes to Pages. Flaky actions
   and low stability go to Flows. No more abstract "Quality" grab-bag.

3. **Graph folds into Flows** as a sub-view. The graph IS the flow/transition
   model. It stays as one full site graph (not per-flow mini-graphs).

4. **The report currently shows crawl data only.** No MBT execution results
   yet. The Testing sidebar section is a placeholder for future work.

5. **`state_to_page_type` mapping** (already implemented) correctly maps
   `state_id -> page_type_id -> graph node` for archetype/quality lookups.

## Data Flow Reminders

- `discovery_timeline` rows have `state_id` (per-state)
- Graph nodes have `id = page_type_id` (per-page-type, NOT per-state)
- `state_to_page_type: Record<string, string>` maps between them
- Multiple states can share one page type (same structural signature)
- Multiple states at the same URL can have DIFFERENT page types
- Page objects (`PageObjectCard`) are keyed by `page_type_id`

## What's Already Done

- [x] `stripPageSuffix` and `shortenFlowName` utilities (format.ts)
- [x] StatCard tooltips
- [x] Issues modal on Summary (click Issues Found stat)
- [x] 6-stat grid (2 rows of 3) with tooltips
- [x] Removed standalone Flows Discovered list from Summary
- [x] Timeline: 2-pill nav (Flows/All Steps), Flows default
- [x] FlowSection: Gherkin rendering, page badges, smart grouping
- [x] PageObjectModal component
- [x] StepDetailModal title stripping
- [x] Low stability sort fix (step_index first, then confidence)
- [x] Title stripping across all tabs
- [x] `</script>` escaping in build.py
- [x] Pages Discovered: expandable rows grouped by URL with States column
- [x] `state_to_page_type` mapping (backend + frontend)

## What's Remaining

- [x] Vertical sidebar layout (AppShell.tsx rewrite)
- [x] Move Pages Discovered table from Overview to new Pages tab
- [x] Build page object cards into Pages tab
- [x] Dissolve Quality tab — move locator health to Pages, flaky/stability to Flows
- [x] Add Site Graph pill to Flows tab (move GraphView)
- [x] Testing sidebar section with empty state placeholder
- [x] Update all tests for new structure
- [x] Make archetype badges clickable (open page object detail)

## File Map (Current)

| Area | File | Role |
|------|------|------|
| Layout | `components/layout/AppShell.tsx` | Sidebar + content area shell |
| Layout | `components/layout/TabBar.tsx` | Horizontal sub-tabs |
| Layout | `components/layout/Sidebar.tsx` | Vertical section nav |
| Tabs | `components/tabs/Summary.tsx` | Overview tab (stats, efficiency, issues) |
| Tabs | `components/tabs/Pages.tsx` | Pages tab (discovery table, page objects, locator health) |
| Tabs | `components/tabs/Timeline.tsx` | Flows tab (flows, site graph, all steps, stability) |
| Tabs | `components/tabs/GraphView.tsx` | Site graph (sub-pill of Flows) |
| Tabs | `components/tabs/TestingPlaceholder.tsx` | MBT placeholder |
| Quality | `components/tabs/quality/LocatorHealth.tsx` | Used by Pages tab |
| Quality | `components/tabs/quality/BlockedPages.tsx` | Used by Pages tab |
| Quality | `components/tabs/quality/Recommendations.tsx` | Used by Pages + Flows tabs |
| Quality | `components/tabs/quality/FlakyActions.tsx` | Used by Flows/Stability pill |
| Quality | `components/tabs/quality/LowStability.tsx` | Used by Flows/Stability pill |
| State | `App.tsx` | Two-tier navigation context (SECTIONS model) |
| Types | `types.ts` | No changes needed |

## Verification

```bash
cd src/flowscout/reporting/dashboard && bun run build
bun run test:run
cd ../../../.. && uv run pytest tests/ -v
uv run flowscout explore https://lgtm-hq.github.io/turbo-themes/ --max-depth 10
# Open report.html and verify:
#   - Sidebar: Exploration active, Testing shows placeholder
#   - Overview: stats, efficiency, issues modal (no pages table)
#   - Pages: discovery table + page object cards + locator health
#   - Flows: flow templates (Gherkin), site graph pill, all steps pill
#   - Flaky actions and low stability live under Flows
```
