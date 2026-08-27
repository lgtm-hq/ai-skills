# ADR 0003: Upstream-native slicing over physical restructure

- Status: Accepted
- Date: 2026-08-27
- Evidence: [plugin-engine-lab DECISIONS.md][lab-decisions]
  (anthropics/skills marketplace; vendor bake slicing)

## Context

Atomic plugins ([ADR 0001](./0001-plugin-canonical-atomic-selection.md))
could mean physically moving each group into its own directory tree. That
would split the first-party `skills/` catalog, break relative links, and
force every skill to pick a single plugin home on disk.

The Claude marketplace format already slices one tree into many plugins:
`source: "./"` plus `strict: false` plus a `skills` array of paths.
anthropics/skills ships five plugins that way. Cursor and Copilot already
read that Claude-format marketplace, so the slice is real for those hosts
without a second tree.

Cursor's own `marketplace.json` plugin-entry schema does not allow a
`skills` array. The generated Cursor adapter is a name-list mirror
(`source: "./"` per group). It does not by itself isolate skills; Cursor
plugin loading of this repo uses the Claude marketplace. Per-group
`.cursor-plugin/plugin.json` directories would be a physical split and
need a new ADR.

## Decision

Slice with **upstream-native marketplace metadata**, not a physical
restructure of `skills/`. First-party groups in `bundles.yaml` become
marketplace plugins that share the repo root and list their skill paths.
`strict: false` means the skills array is authoritative for Claude;
plugin.json does not have to enumerate components.

Vendor bake may copy a subset into a new tree when the vendor is a loose
skills repo. That is a bake-time mapping, still declared in the registry,
not a reason to split first-party skills on disk.

## Consequences

- One `skills/<name>/SKILL.md` tree remains the authoring layout.
- Marketplace `name` is the kebab-case plugin id; display names stay
  human-readable on hosts that accept `displayName`.
- Skills listed under `ungrouped` stay out of generated manifests. The
  current gateway still shows them in an "Other" bucket; plugin-only
  selection (issue #373) will not offer skill-level cherry-picks — they
  join a plugin or stay unavailable.
- A later physical split is a new ADR, not a silent follow-up.

[lab-decisions]: https://github.com/lgtm-hq/plugin-engine-lab/blob/main/DECISIONS.md
