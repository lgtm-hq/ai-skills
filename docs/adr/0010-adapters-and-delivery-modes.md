# ADR 0010: Adapters, delivery modes and recovery

- Status: Accepted
- Date: 2026-11-01

## Context

Hosts have different destinations, configuration ownership and recovery limits.
An installation needs an inspectable plan and durable recovery, including when
an external host CLI fails after changing state. Capability evidence and policy
remain separate inputs as established by
[ADR 0004](./0004-doctor-capability-probe.md). Terms follow the
[glossary](../glossary.md).

## Decision

### Adapter contract and delivery

An adapter provides, in order, a support report, a plan, reversible operations,
verification and recovery guarantees. Its support report uses
[ADR 0009](./0009-capabilities-and-parity.md). The registry validates the adapter
contract at registration time; the core contains no host-specific branches.
Unsupported or policy-denied plans fail before writes.

The modes are `native-plugin`, `user-explode` and `repo-materialize`. The canonical
scope rule is
[ADR 0001](./0001-plugin-canonical-atomic-selection.md); adapters apply that rule.
Policy selects the permitted delivery as in ADR 0004.

Native delivery installs only the resolved, filtered and pinned artifact as a
generated plugin, never an upstream plugin. First-party content goes through
the same build defined by
[ADR 0011](./0011-manifest-provenance-locks-artifacts-trust.md).
`user-explode` delivers capabilities and resources to user destinations;
`repo-materialize` delivers them into a repository.

For `repo-materialize`, the default is excluded output: create only new untracked
paths and list them in `.git/info/exclude`. Committed output requires the
repository's own `ai-skills.yaml` opt-in. Writing into a tracked file requires
committed mode; otherwise the cell is `policy-blocked`. A hand-written
`AGENTS.md`-style file gets a separate instruction file where that route is
verified, or a managed marker block with explicit opt-in. Preserve surrounding
bytes. Marker-block consent does not bypass the tracked-file guard.

### Ownership and recovery

Machine-local receipts record owned paths and configuration keys, owners,
previous hashes, aliases, scope, and adapter and policy fingerprints. They also
retain the installed hashes needed to detect subsequent edits. A durable journal
records operations and recovery progress so a crash can resume the plan or
compensate completed operations. `rollback` undoes the last generation using the
journal and receipts, subject to the same ownership and hash guards.

The plan's atomic installation guarantee in
[ADR 0001](./0001-plugin-canonical-atomic-selection.md) does not claim atomicity
across external host CLIs. Each adapter describes compensating operations,
recovery limits and irreversible effects in its plan and reports any remaining
effects after failure or rollback. Recovery never silently claims full success
when compensation is incomplete.

Remove only owned content whose current hash matches the recorded installed
hash, including configuration entries owned by key. Preserve and report changed
or unowned content rather than deleting it. Aliases and collision declarations
follow [ADR 0005](./0005-collision-doctrine.md).

The host registry models cross-host reads, including `~/.agents/skills`, so a plan
does not deliver the same content twice through overlapping destinations.
Recorded Cursor reads from `~/.claude/skills` and `~/.agents/skills` establish
those routes, without claiming duplicate execution was measured. Planning must
account for all readers of a shared destination when assessing scope and policy.

A skills-CLI backend must meet this entire adapter contract. Otherwise it is an
explicitly unmanaged handoff: report that ownership, verification and recovery
guarantees are unavailable, without issuing a managed receipt or claiming a
managed installation.

## Consequences

- Plans expose destination changes and recovery limits before application.
- Registries centralize host behavior; new adapters do not add host branches to
  the core.
- Receipts complement the committed lock in ADR 0011; they cannot substitute for
  its reproducible artifact selection.
