# ADR 0005: Qualified identity, persistent aliases and explicit conflicts

- Status: Accepted (amended 2026-11-01)
- Date: 2026-08-27
- Amends: Qualified IDs and persistent destination aliases replace bare-name
  identity; configuration conflicts require persisted overrides.
- Evidence: [plugin-engine-lab DECISIONS.md][lab-decisions]
  (historical collision classes 1–3)

## Context

Different packages can publish capabilities with the same short name.
Generated plugin envelopes may namespace them, while another delivery
mode or host index exposes a shared name. Bare names therefore cannot
serve as stable identity. Resource paths and configuration keys can also
clash with existing local content in the requested scope.

Silent conflict resolution can change behavior or destroy local work.
Repeated prompts do not support reproducible fleet installs: conflict
answers must be declarations that every run can replay.

## Decision

Evaluate collisions on qualified IDs first, then on host-visible names
and destination paths through the adapter. A rename is a persistent
destination alias, preserving the qualified capability ID and provenance.

Keep three content classes:

1. **Identical incoming content vs unowned local content** — dedupe by
   content hash. Skip and report the incoming copy without claiming
   ownership; later removal cannot delete the local copy. Identical
   catalog content still needs the namespace report and explicit aliases
   or selection so package ownership remains unambiguous.
2. **Different content across catalog packages** — never auto-resolve.
   Declare a destination alias or select one side out. Build and CI emit
   a global namespace report and fail on unresolved collisions.
3. **Catalog vs local machine content** — install-time detection is the
   second line because CI cannot inspect the destination. Different
   content fails the plan without an explicit persisted resolution;
   identical unowned content follows class 1.

Configuration entries, including MCP servers and hooks, are owned by
key. A conflicting key fails the plan unless a persisted `overrides:`
declaration resolves it. Non-interactive runs (`-y` and CI included)
replay declarations or fail with the report. The interactive prompt
writes the same declarations for keep-both / pick-one decisions.

Removal deletes only owned content whose current hash matches the
recorded hash. Matching a name or alias alone never authorizes removal.

## Consequences

- Bake and CI check catalog collisions; destination adapters check
  local conflicts before an atomic plan changes disk
  ([ADR 0001](./0001-plugin-canonical-atomic-selection.md)). Updates
  obey the same collision and owned-plus-hash removal rules.
- [#385](https://github.com/lgtm-hq/ai-skills/issues/385) implements
  interactive resolution persisted as replayable overrides and aliases.
- [#383](https://github.com/lgtm-hq/ai-skills/issues/383) applies key
  ownership and explicit conflict resolution to lifecycle and integration
  roles under trust policy.
- [#565](https://github.com/lgtm-hq/ai-skills/issues/565) defines qualified
  identity, adapter and declaration contracts without changing this doctrine.

[lab-decisions]: https://github.com/lgtm-hq/plugin-engine-lab/blob/main/DECISIONS.md
