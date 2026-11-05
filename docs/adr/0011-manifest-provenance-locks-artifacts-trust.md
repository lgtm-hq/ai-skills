# ADR 0011: Manifest, provenance, locks, artifacts, transports and trust

- Status: Accepted
- Date: 2026-11-01

## Context

A repository can publish packages, consume vendors and re-export capabilities.
Consumers need reproducible artifacts and provenance that survives copying,
while keeping executable content subject to their own policy. The
[glossary](../glossary.md) defines the shared vocabulary; projection semantics
belong to [ADR 0009](./0009-capabilities-and-parity.md), delivery and recovery to
[ADR 0010](./0010-adapters-and-delivery-modes.md).

## Decision

### Manifest and identity

`ai-skills.yaml` is governed by a JSON Schema and contains `apiVersion`,
`packages`, `vendors` (pinned imports with `include`/`exclude`), explicit
`exports`, `policy` and `overrides`. Importing never re-publishes content;
re-export requires an explicit export. Consumers map vendors without manifests.
A vendor manifest can never grant trust or loosen consumer policy.

Vendor SHA source is a direct, unescaped 40-hex scalar, plain or ordinary
single/double quoted, without escape sequences, folded/block scalars, anchors,
aliases or tags. Manifest loading enforces this before compatibility publication;
native Renovate YAML/JSONata discovery decodes other fields while its updater can
replace exactly one vendor's SHA (owner decision, 2026-11-03,
[#568](https://github.com/lgtm-hq/ai-skills/issues/568#issuecomment-6597021588)).

Vendor `sha` and `branch` strings must be quoted whenever their plain spelling
is read differently by our PyYAML loader and Renovate's pinned YAML parser.
Writers preserve the semantic string and quote these values; validation rejects
ambiguous unquoted source before compatibility publication, without writing any
output, and names the field and quoted fix. This is a general parser-divergence
rule, including scientific notation, YAML 1.2 octal and leading-zero decimal
numbers; explicit YAML 1.1 directives also affect resolution. For example, use
`sha: "1e11111111111111111111111111111111111111"` and `branch: "0o17"`.
Writers escape Unicode line breaks in these fields to preserve the exact string
across both parsers' different line folding rules.
Future divergence cases in these two fields are covered by the same rule.
All other fields retain their existing validation rules (owner decision,
2026-11-03,
[#568](https://github.com/lgtm-hq/ai-skills/issues/568#issuecomment-6601721842)).

IDs are qualified and stable across path and display-name changes. They do not
depend on content hashes. An identity change is a remove plus an add unless
explicitly migrated. Selection follows
[ADR 0001](./0001-plugin-canonical-atomic-selection.md); destination aliases
follow [ADR 0005](./0005-collision-doctrine.md).

### Provenance

Each capability carries its origin and the chain of intermediate publishers;
resource lineage survives copying. Denies match anywhere in the chain, and a
re-exporter cannot override them. A hash match against a publisher's declared
inputs without lineage raises a missing-lineage diagnostic, which fails under
strict policy. This catalog's own CI runs strict.

An independently authored attestation is possible; consumer policy decides
whether it clears that failure. An override never erases known lineage.
Provenance is an authenticated declaration, not a detector. License and notice
obligations propagate through imports and re-exports.

### Locks and artifacts

`ai-skills.lock` is committed deterministic JSON, recording revisions, artifact
and tree digests, lineage, filters, closure, and schema and builder versions.
Receipts in ADR 0010 are its machine-local counterpart. Unknown lock or receipt
versions fail. Individuals without a repository use the consumer profile at
`~/.config/ai-skills/selection.yaml`.

An artifact is a deterministic tarball plus an index, with per-capability
dependency and resource closures and lineage. Bake materializes shared resources
into `_shared/`, rewriting only structurally understood references. A reference
that cannot be rewritten makes its capability `source-unportable`.

The committed tree digest is checked at release, extending the publish-time
artifact decision in [ADR 0007](./0007-publish-time-vendor-bake.md). The lock
commits the digest; bake output remains uncommitted. SemVer advice comes from the
bake diff: removals, broken `requires`, and widened activation or permissions
count as major. The engine, schema and packages are versioned separately.

### Transports and trust

An artifact can arrive through a git marketplace repository, npm (including
private mirrors), a release asset or an offline file. Restricted policy permits
no install-time network bootstrap. Verify attestations when policy requires it.

Executable content is denied by default. Trust grants are specific to capability,
origin, digest, command, endpoint and event; new execution surface invalidates a
grant. Nothing from a vendor runs during fetch, build or install. Flag unpinned
`npx`, `uvx` and `docker` commands; policy can forbid them. Secrets are referenced
externally.

### Commands

| Command                       | Contract                                                                                         |
| ----------------------------- | ------------------------------------------------------------------------------------------------ |
| `init`                        | Create a publishing or consumer manifest/profile.                                                |
| `validate`                    | Validate declarations against the schema and policy.                                             |
| `add`                         | Declare a package or pinned vendor import.                                                       |
| `lock`                        | Record resolved selection in the lock.                                                           |
| `build`                       | Build the artifact offline from locked, locally available inputs.                                |
| `repin`                       | Update pins with a bake diff and advisory SemVer.                                                |
| `plan`                        | Explain the build-plane resolution and policy trace.                                             |
| `install --dry-run`           | Show the install-plane filter result and adapter plan.                                           |
| `install`, `update`, `remove` | Apply adapter plans under ADR 0010.                                                              |
| `doctor`, `doctor --report`   | Inspect evidence and recorded state; report as in [ADR 0004](./0004-doctor-capability-probe.md). |
| `rollback`                    | Recover the last generation under ADR 0010.                                                      |
| Frozen restore                | Restore locked inputs and selection; fail rather than repin or resolve missing inputs.           |

## Amendment: source scope and artifact-only resources (2026-11-04)

[Owner decision A](https://github.com/lgtm-hq/ai-skills/issues/573#issuecomment-6627648836)
supersedes the earlier re-export comparison scope. An authenticated, verified
re-export is compared with the declared inputs of its actual source publisher.
Recursive source validation performs that comparison before publication. Locally
authored and unbound catalog copies still compare against every declared catalog
input, including unselected files. Equal bytes never establish sibling ancestry.
Origin denies, index authentication and attestation-conflict checks remain in
force; this amendment adds no size, filename, vendor or policy exceptions.

Manifest v1 packages and mapped packages may declare `artifactResources` with
`version: 1`, a `resources` list of explicit `{id, path}` records, and `bindings`
mapping local `role/name` identities to resource ID lists. Each binding enumerates
the complete transitive resource closure for that capability; the engine never
discovers or silently adds dependencies. Directory declarations include their
entire safe tree. Every structural local reference in each projected resource
(CommonMark destinations and declared `x-resource-paths` scalar fields) must
resolve to that capability or a resource in its declared closure. Missing,
undeclared and unsafe targets fail the build, including references several hops
away. Cycles are permitted only when their complete closure is declared.

Projection feeds the normal inventory, selection, ingestion, lineage, deny and
legal-notice gates, and materializes resources under `<capability>/_shared/`.
The compatibility writer explicitly ignores `artifactResources`. Legacy
registries and `plugins-baked/` retain their bytes and semantics and **do not
deliver these dependencies**. Ordinary `resources`, `extraFiles` and `requires`
retain their existing legacy representability checks. This is a separate
publication contract, not permission to discard ordinary dependencies.

## Amendment: resolution lock v1 (2026-11-04)

Issue #574 implements `ai-skills.lock` as `lockVersion: 1`. Besides `builder`
(`engineVersion`, `artifactFormat`), `vendors` (`id`, `repo`, `sha`,
`sourceDigest`, `filters`) and `packages` (`id`, `version`, `artifactDigest`,
`treeDigest`, `capabilities` with `closure` and `lineage`), it records:

- `manifest.digest` over the canonical parsed manifest, so key order and
  formatting never change the lock, and `manifest.inputsDigest`, the offline
  author-input fingerprint previously committed by `artifact-digests.json`.
- Package `resources` with their index lineage, so standalone and artifact-only
  resources keep authoritative lineage. Closures and lineage are copied from the
  built index and never inferred from equal bytes.

`sourceDigest` hashes a canonical tar of the extracted tree, not the forge
archive. Unknown versions, unknown keys and duplicate keys fail. The source cache,
`lock`/`build` contracts and CI gates are described in
[the artifact contract](../artifacts.md#resolution-lock-and-source-cache) and the
[ADR 0007](./0007-publish-time-vendor-bake.md) amendment.

## Consequences

- Publication and consumption share a reproducible contract without inheriting
  vendor authority.
- These contracts follow the Accepted bundled-Python engine and thin TypeScript
  launcher decision in
  [ADR 0008](./0008-engine-runtime-build-and-install-planes.md), preserving its
  build/install boundary. No additional deployment measurement is implied.
