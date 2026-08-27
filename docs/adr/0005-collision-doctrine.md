# ADR 0005: Collision doctrine: hash, registry rename, CI report, install line

- Status: Accepted
- Date: 2026-08-27
- Evidence: [plugin-engine-lab DECISIONS.md][lab-decisions]
  (collision classes 1–3; interactive choice deferred to post-v1)

## Context

Native plugins namespace skills per plugin. Explode and some host indexes
use a global name. Real vendors collide: `teach` (three-way), `handoff`,
`tdd`. Identical content also appears twice (pstack `unslop` vs a local
copy that was the same bytes).

Auto-resolving different content silently corrupts installs. Prompting on
every update is unusable for org fleets. cursor-toolkit's keep/replace
flow exists but does not persist answers.

## Decision

Three classes, three mechanisms:

1. **Identical content, same name vs unowned local** — auto-dedupe by
   content hash. Skip the incoming copy; do not claim ownership so later
   remove cannot delete the user's file. Log line only. Catalog-vs-catalog
   byte-identical names still go through the CI namespace report (class
   2): two plugins must not share an explode name without a registry
   rename or slice, even when the bytes match, or removing one plugin
   would strand the other.
2. **Different content, same name across catalog plugins** — never
   auto-resolve. Declare `renameSkills: {old: new}` (or equivalent) in
   the registry; bake renames the directory and the SKILL.md frontmatter
   `name`. Alternative: slice one side out. CI emits a **global
   namespace report** across baked plugins and fails loud.
3. **Catalog vs local machine content** — CI cannot see laptops.
   Install-time detection is the second line: hard error on different
   content, dedupe on identical.

Component defaults: agents collide like skills; hooks merge by event
append; MCP server keys first-wins, never overwrite.

Interactive keep-both / pick-one, with answers persisted as declarations,
is **post-v1 backlog** (epic #381 rules). V1 is registry + CI report +
install-time second line. Non-interactive / `-y` / CI replays recorded
decisions or fails with the report, never prompts.

## Consequences

- Bake and CI own catalog-vs-catalog collisions; the installer owns
  catalog-vs-local.
- Cleanup and remove whitelist by lock ownership and verify hash before
  `rm` — matching a vendor name is not enough (orphan-cleanup deleted a
  local `unslop` in the lab).
- Engine `update` is versioned remove + reinstall via the same projector;
  collision rules apply on the way in.

[lab-decisions]: https://github.com/lgtm-hq/plugin-engine-lab/blob/main/DECISIONS.md
