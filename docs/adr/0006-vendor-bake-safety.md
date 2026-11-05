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

**Reject** symlinks at bake time, with two documented exceptions.
Content-free navigation aliases outside every ingested tree (declared
skill roots, plugin `skillsRoot` paths, and plugin `extraSkills` paths)
— upstream repositories
commonly alias docs such as `AGENTS.md -> CLAUDE.md` — are **unlinked**
(not followed) with a `dropped non-skill symlink` notice in the bake
log, so an escaping alias is removed rather than resolved. Links inside
an ingested tree, and links on the path to a root (an ancestor of a
globbed `skillsRoot`), still fail the bake: dropping an ancestor would
silently shrink what a glob matches. Second, a wildcard-selected skill
whose `SKILL.md` frontmatter is unusable is skipped with a printed
reason instead of failing the vendor; explicit skill lists, `extraSkills`,
and declared renames still fail hard. Internal references must resolve
inside the plugin. SKILL.md must be present for ingested skills.

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

## Ingest limits and content checks

Ingestion treats every vendor byte as untrusted and never runs package lifecycle
scripts, Python setup files, Makefiles or executable hooks. Checks apply to both
pinned downloads and explicit offline trees, including public ingestion APIs.

Defaults are 100 MiB compressed download, 20,000 archive headers (including
extended headers), 25 MiB per member, 500 MiB inflated archive and a 100:1 inflated
to compressed ratio. Inflated bytes include metadata, padding and trailing data:
these also consume runner resources. Downloads are read in bounded chunks and an
oversized Content-Length is rejected before reading. Decompression is bounded
before tar processing, and headers are checked before PAX/GNU metadata allocation.
Hard links, devices, FIFOs and sparse entries are rejected. A complete preflight
precedes extraction with the data filter into a private staging tree.

Only selected plugin payloads receive content checks: 5 MiB per file, 50 MiB per
plugin, Git LFS pointer rejection and versioned secret-shape rules. Nothing fetches
LFS objects. A NUL in the first 8 KiB marks a binary file. Text tripwires cover PEM
private keys and AWS, GitHub, Slack, Google, npm, Stripe, Anthropic and OpenAI key
shapes. Diagnostics contain path, line and stable rule ID, never matched values.
Reasons and other report context are redacted too. Scanning is a **tripwire, not a
trust guarantee**: it neither proves absence of secrets nor approves vendor code.

Consumer-owned `vendors[].ingestLimits` may override individual positive integer
limits (`downloadBytes`, `archiveMembers`, `archiveBytes`, `memberBytes`,
`compressionRatio`, `fileBytes`, `pluginBytes`) with a required nonblank `reason`.
`vendors[].ingestAllow` acknowledges `{path, rule, sha256, reason}` for a specific
published file. Bake paths are plugin-relative, after slicing and renaming, and
SHA-256 covers the exact published bytes, including rewritten skill frontmatter.
Inventory paths refer to the original repository bytes it observes. Changes to
path, rule or bytes invalidate an acknowledgement. Own-package acknowledgements
are represented by `overrides.ingestAllow` for the manifest validation workflow.
Vendor-supplied policy never grants consumer trust. These fields survive the
manifest-to-legacy projection and are parsed strictly by the registry reader.

Setuid, setgid and sticky bits are rejected before tar filtering or offline copying.
Regular ingested files become 0755 when owner-executable, otherwise 0644, matching
inventory's Git-like mode identity. Inventory observes without chmodding inputs.
Transactional backup and rollback copies retain their exact original modes.

Clarifications (2026-11-05, #634; no decision change): archive member names and
symlink targets containing a backslash, an absolute path or a `..` segment are
rejected on every platform. The special-bit check covers every directory and file of
the archive or offline tree, including the root and unselected paths, so a tree
created beneath a setgid directory inherits the bit and is rejected. Secret rules
anchor on word boundaries: a shape glued to an adjacent letter, digit or underscore
(for example `X_AKIA…`) is not reported. The PEM rule covers `BEGIN [TYPE ]PRIVATE
KEY` with at most one type word, not OpenPGP `PRIVATE KEY BLOCK` armor. File names
are never scanned, although diagnostics redact secret-shaped names. Content scans
reuse `archiveMembers` as the per-package or per-plugin file-count bound.

`BAKE.json.ingestChecks` and the coverage report's "Ingest checks" section record
the rule-set version, effective limits and acknowledged findings. Offline `--check`
re-scans and bounds actual bytes with the current registry policy before trusting
lock digests. Editing the lock cannot grant an acknowledgement, increase limits or
hide a finding. Rejection never publishes a partially baked plugin tree.
