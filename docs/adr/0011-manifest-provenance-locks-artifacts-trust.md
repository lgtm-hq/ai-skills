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

## Consequences

- Publication and consumption share a reproducible contract without inheriting
  vendor authority.
- These contracts follow the Accepted bundled-Python engine and thin TypeScript
  launcher decision in
  [ADR 0008](./0008-engine-runtime-build-and-install-planes.md), preserving its
  build/install boundary. No additional deployment measurement is implied.
