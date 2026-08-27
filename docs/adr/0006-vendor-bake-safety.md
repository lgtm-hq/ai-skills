# ADR 0006: Vendor bake safety: no execute, path rejection, coverage reports

- Status: Accepted
- Date: 2026-08-27
- Evidence: [plugin-engine-lab DECISIONS.md][lab-decisions]
  (coverage report; symlink/path-escape validation; caveman hooks)

## Context

Vendor repos are not a mirror of this catalog. Formats vary: loose
`skills/` trees, nested categories, Cursor-only manifests, executable
hooks (caveman SessionStart node scripts), placeholders under
`template/`, unsupported `automations/`.

A bake that copies blindly can ship path-escaping symlinks, run vendor
code during install, or drop SKILL.md files with no record of the skip.
Silent exclusion hid both skipped content and duplicates the collision
guard later disproved.

The engine must consume bake output as ordinary plugins
([ADR 0002](./0002-neutral-metadata-generated-adapters.md)) — no
vendor-shaped special case at runtime.

## Decision

Bake is a **curation contract**, not a mirror. Ingest exactly what the
vendor-plugin registry (issue #377) declares. The lab used `skillsRoot` +
`"*"` or paths, `extraSkills`, and `agents` — that is the #377 schema,
not today's index-only `skillRoots` list in `vendors.yaml`. No semantic
guessing: location carries meaning.

**Never execute vendor content** during bake or install. Hooks and other
runnable vendor files are an explicit trust decision; default is omit
(caveman baked skills-only in the lab).

**Reject** symlinks and path escapes at bake time. Internal references
must resolve inside the plugin. SKILL.md must be present for ingested
skills.

**Exclusion is fine; silent exclusion is not.** Every SKILL.md in the
vendor tree that is not ingested is listed as SKIPPED in a coverage
report that belongs in the bake log / PR diff. Vendors that fit no
declarable convention get a purpose-built adapter or are declined.

Write bake output to a temp directory and swap atomically. A partial
`plugins-baked/` tree is not a marketplace.

## Consequences

- First-party and baked vendors are indistinguishable downstream.
- Coverage + collision guard are the line-drawing mechanism: the report
  forces a look; the guard stops wrong "second root" conclusions.
- Registry entries pin repo + SHA + file→plugin mapping (issue #377).
- Re-pin / update (issue #380) re-runs the same bake; skipped paths stay
  reviewed, not forgotten.

[lab-decisions]: https://github.com/lgtm-hq/plugin-engine-lab/blob/main/DECISIONS.md
