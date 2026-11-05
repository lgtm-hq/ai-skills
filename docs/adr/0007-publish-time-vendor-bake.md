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
(`vendors.yaml`, `bundles.yaml`, vendor-indexes, `NOTICE.md`) are unchanged.

## Consequences

- Vendor-definition and re-pin PRs shrink to authored substance. The pin
  SHA is the supply-chain review point.
- Rebuilds of a past release no longer depend on GitHub still serving the
  vendor repo at the pinned SHA. A warm source cache, or a mirrored copy of
  one, rebuilds offline: `ai-skills-engine build` reads only the committed
  `ai-skills.lock` and digest-verified cached sources (see the resolution
  lock amendment below). Only a cold cache needs the forge, and fetched bytes
  must still match the locked `sourceDigest`. The published npm tarball
  remains the immutable artifact.
- Retaining vendor content long-term means promoting it to first-party
  `skills/`, not keeping a stale pin so an old bake stays in git.
- Offline clones cannot inspect baked vendor trees until they bake (or
  unpack a published package).

## Amendment: reviewed capability artifact digests

The capability build defined by ADR 0011 additionally emits canonical,
uncompressed package tarballs and schema-validated indexes under
`dist/artifacts/`. These payloads remain uncommitted, as does `plugins-baked/`.
Their release identity is the SHA-256 of the uncompressed tar, independent of
compression choices. The tar digest is external to its index to avoid a
self-reference.

A generated, committed `artifact-digests.json` recorded each selected package's
tree digest and external tar digest (superseded by `ai-skills.lock`; see the
resolution lock amendment below). Updating pins, selected payloads, source
resources or builder inputs requires regenerating this commitment from a valid
selection. Validation checks local author-input drift offline. Publishing must
also rebuild with complete pinned inputs and compare the regenerated commitment;
missing inputs, strict provenance failures and any mismatch fail closed. An
absent commitment cannot authorize publishing. Issue #574 incorporates this
commitment into `ai-skills.lock`.

The compatibility marketplace bake retains its existing bytes and safety rules.
[The artifact contract](../artifacts.md) documents the separate build command,
resource layout and downstream golden fixtures.

### Amendment: artifact-only dependency projection (2026-11-04)

[Owner decision A](https://github.com/lgtm-hq/ai-skills/issues/573#issuecomment-6627648836)
adds the versioned `artifactResources` declaration described in ADR 0011. Its
complete, explicitly enumerated resource closure is delivered only by capability
artifacts. The compatibility writer ignores that declaration by contract;
legacy `plugins-baked/` and generated registries retain their bytes and semantics
and do not deliver these dependencies. Ordinary dependency-loss rejection remains
unchanged. Real pinned catalog builds, offline input checks and public rebuild
checks must pass before accepting the generated root digest commitment.

### Amendment: release builder version commitment (2026-11-04)

Every tar index records the installed engine's `engineVersion`, so a project
version bump changes every external `artifactDigest` even when package tree
digests stay equal. The release version PR must contain the regenerated
`artifact-digests.json` for that new builder identity.

The release workflow's `scripts/ci/update_release_version.sh` hook runs after
the Python ecosystem updater changes `pyproject.toml` and `uv.lock`. It preserves
the README and marketplace restamps, installs the bumped project with
`uv sync --locked`, and runs the public
`ai-skills-engine build --fetch-vendors --write-digests` command. The reusable
workflow captures the hook's tracked-file changes into the same version PR;
installation, acquisition or build failure stops PR preparation. The shared uv
bootstrap uses the repository's existing version and installer checksum pins.

This chooses regeneration in the version PR instead of adding a second version
field to the commitment. Review covers the regenerated identity before release;
publishing still rebuilds pristine pinned inputs with `build --fetch-vendors
--check` and fails closed on any difference. Offline `--check-inputs` continues
to detect local author-input drift without acquiring vendor sources.
Issue #574 later moved this commitment into `ai-skills.lock` and replaced these
commands with `lock`, `lock --fetch`, `lock --check` and an offline `build`.

## Amendment: resolution lock and frozen source cache (2026-11-04)

Issue #574 replaces `artifact-digests.json` with the committed, deterministic
`ai-skills.lock` defined by ADR 0011. The lock records the builder identity, the
digest of the parsed manifest (independent of YAML key order), the digest of
local author inputs, each pinned vendor's `sourceDigest` and filters, and each
package's `artifactDigest`, `treeDigest`, capability closures and index lineage.
The `sourceDigest` hashes a canonical tar of the extracted tree, so forge
re-compression never changes it. Machine-local install receipts are a separate
file and never mix with the lock.

Resolution and building are separate. `ai-skills-engine lock` resolves changed
manifest entries, fetches missing sources into the content-addressed cache at
`${AI_SKILLS_CACHE:-${XDG_CACHE_HOME:-~/.cache}/ai-skills}` and never moves an
existing pin; repinning stays a separate command. `lock --fetch` fills the cache
for the existing lock only. `lock --check` writes nothing and fails on a stale
lock or any difference from a cache-only rebuild; `--inputs-only` performs the
offline checkout drift check without vendor sources. `ai-skills-engine build`
never resolves or fetches. It refuses a stale or non-canonical lock with a
`lock` hint and any missing or corrupted cache entry with a `lock --fetch` hint,
and it publishes
`dist/artifacts/` only when every rebuilt digest equals the lock. Cache reads
re-verify digests; cache writes use a temporary file, fsync and rename, so
concurrent CI jobs are safe. The compatibility vendor bake reads pinned trees
through the same cache.

`scripts/validate.sh` runs `lock --check --inputs-only`. CI's lock gate and
`publish-npm.yml` run `lock --fetch`, `lock --check` and `build`; publishing
fails closed if any `artifactDigest` differs. The release version hook
regenerates the lock for the new builder identity with `ai-skills-engine lock`.
`ai-skills-engine bake artifacts` remains an explicit-input development writer
that never reads or writes the lock.
