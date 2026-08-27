# ADR 0001: Plugin as the canonical artifact; atomic plugin-only selection

- Status: Accepted
- Date: 2026-08-27
- Evidence: [plugin-engine-lab DECISIONS.md][lab-decisions]
  (settled going in; Final Agreements item 3)

## Context

The catalog used to treat a skill directory as the unit of install. The
gateway exploded skills into host-native dirs (`~/.agents/skills` and
symlinks). That model does not match how Claude Code, Cursor, and Copilot
actually load content: they install **plugins** (a manifest plus a tree of
skills, agents, commands, hooks, MCP).

Explode still exists as a last-mile projection for hosts that cannot load
plugin dirs. In the lab it lost to native plugins on namespacing, grouping,
and transactional install: collisions aborted mid-copy and left orphan
skill dirs the lockfile never tracked. Cherry-picking skills out of a
plugin is the same class of partial tree; the engine does not offer it.

## Decision

A **plugin** is the canonical artifact and the only user-facing selection
unit. A plugin is a distribution envelope, not a completeness requirement:
it holds whatever mix of components its *job* needs.

Installs are atomic. Marketplace = store, plugin = product, components =
ingredients: contents stay visible; users do not cherry-pick. Granularity
is solved by slicing smaller plugins at the registry or bake layer.

Explode is a delivery projection, not the model. It survives only as a
doctor-gated fallback for hosts without plugin loading (see
[ADR 0004](./0004-doctor-capability-probe.md)). The post-install escape
valve is per-component *disable* (MCP/hooks), never a partial install.
That disable path is post-v1 backlog, not a v1 engine feature.

## Consequences

- `bundles.yaml` groups are plugins: kebab-case `id`, display name,
  description, skill list.
- Gateway UX lists plugins, not a flat skill cart (epic issue #373).
- Vendor content is baked into the same plugin shape; the engine sees one
  input format ([ADR 0006](./0006-vendor-bake-safety.md)).
- Breaking gateway changes document "wipe and reinstall" in the changelog
  rather than a migration engine. One user, acceptable.

[lab-decisions]: https://github.com/lgtm-hq/plugin-engine-lab/blob/main/DECISIONS.md
