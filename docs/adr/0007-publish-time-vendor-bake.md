# ADR 0007: Vendor bake output is a publish-time artifact, not repo content

- Status: Accepted
- Date: 2026-08-31
- Supersedes: committed `plugins-baked/` placeholders from issue #378 / PR #411

## Context

The bake pipeline from issue #378 wrote canonical plugin trees under
`plugins-baked/` and treated `--check` as a committed-tree drift gate.
The first real vendor bake (issue #379, attempted in PR #415) produced a
thousand-file PR of which ~25 files were authored. The pin SHA in
`vendors.yaml` already determines the baked content; a 600-file baked
diff on every re-pin is rubber-stamp noise that looks like review without
being one.

The same third-party content would also land a second time under
`npm/ai-skills/data/` via the package sync. Git history would retain
every copy of every re-pin. Bake safety (symlink/path-escape rejection,
executable exclusion, coverage + collision reports) is deterministic from
the pin; committing the output adds no safety.

Wanting to retain an older vendor version is a product decision. Decisions
belong in the repo as first-party content (`skills/`), not as a side
effect of a stale pin.

## Decision

**Do not commit bake output.** `plugins-baked/` and the vendor-derived
`npm/ai-skills/data/plugins-baked/` copy are gitignored. The repo carries
`vendors.yaml` pins and the bake machinery. CI runs a real bake (network
fetch at the pinned SHA) and fails closed on validation, collisions, or
unsafe trees. Coverage and collision reports are CI job output, reviewed
when a PR touches pins or slices.

**Publish bakes, then syncs.** `.github/workflows/publish-npm.yml` runs
`scripts/bake_vendor_plugins.py` before
`scripts/ci/npm/sync_ai_skills_package.py`. The sync copies the fresh
tree into the npm package. Published tarballs are the immutable record of
what shipped.

**`--check` validates a local tree, not git.** When `plugins-baked/` is
absent, `--check` succeeds after confirming no leftover bake sidecars.
When the tree is present (after a local bake or the CI/publish gate),
`--check` re-validates it offline. First-party npm sync checks
(`vendors.yaml`, bundles, vendor-indexes, `NOTICE.md`) are unchanged.

## Consequences

- Vendor-definition and re-pin PRs shrink to authored substance. The pin
  SHA is the supply-chain review point.
- Rebuilds of a past release depend on GitHub still serving the vendor
  repo at the pinned SHA. If that object disappears, that release cannot
  be re-baked from the repo; the published npm tarball remains the
  immutable artifact.
- Retaining vendor content long-term means promoting it to first-party
  `skills/`, not keeping a stale pin so an old bake stays in git.
- Offline clones cannot inspect baked vendor trees until they bake (or
  unpack a published package).
