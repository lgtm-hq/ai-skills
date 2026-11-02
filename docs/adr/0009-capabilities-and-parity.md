# ADR 0009: Capabilities, dialects and parity

- Status: Accepted
- Date: 2026-11-01
- Evidence: [Host evidence format](../parity/evidence-format.md) and
  [recorded findings](../parity/README.md)

## Context

A capability's meaning must survive delivery to a host. File discovery,
successful registration and invocation are different observations; none alone
establishes every semantic guarantee of a role. Policy restrictions also differ
from host limitations. The [glossary](../glossary.md) defines the vocabulary.

## Decision

### Roles and projection

Each capability has one of six roles and a source dialect recorded separately
from its role. A dialect describes source syntax and conventions, not behavior.

| Role          | Payload semantics                                                           |
| ------------- | --------------------------------------------------------------------------- |
| `skill`       | Reusable instructions and resources, with declared invocation restrictions. |
| `instruction` | Instructions with declared scope and activation conditions.                 |
| `specialist`  | Delegated task instructions, configuration and permissions.                 |
| `workflow`    | An invocable procedure with declared invocation semantics.                  |
| `lifecycle`   | Event registrations and the actions those events trigger.                   |
| `integration` | A command or endpoint and its connection configuration.                     |

Dependencies are declared edges: `requires` is hard and expands the dependency
closure; `related` is soft and never cascades. Name and link scanning is lint
only and cannot create dependency edges.

Dropping invocation restrictions, activation scope or permissions is a semantic
change. Strict projection rejects that change; a warning never authorizes
widened activation. Every host-only field, such as `disable-model-invocation`,
needs an explicit projection rule per host. Copying an unrecognized field is
not proof that the host enforces it.

### Parity and evidence

A parity cell is keyed by **host product/interface × version × OS × scope ×
mode × role**. Product and interface are distinct: CLI evidence does not certify
an IDE. Policy-specific assessments retain a separate policy dimension and
never overwrite the underlying cell identity.

| Cell state             | Meaning                                                                                                |
| ---------------------- | ------------------------------------------------------------------------------------------------------ |
| `supported`            | Invocation preserves the tested semantics, with successful removal and verification.                   |
| `partial`              | Some behavior is observed; name lost fields and remaining semantic uncertainty.                        |
| `unverified`           | No safe or conclusive verification; a reason is required.                                              |
| `platform-unavailable` | A tested prerequisite is absent on this OS.                                                            |
| `policy-blocked`       | Engine policy denies a plan, or host policy denies a route with measured or sourced attested evidence. |
| `source-unportable`    | A demonstrated source requirement cannot survive projection.                                           |
| `adapter-missing`      | The host route or its necessary projection is absent.                                                  |

Adopt the [evidence record format](../parity/evidence-format.md), including its
minimal IDE/policy extension. Each cell retains `checkedOn`, `recheckBy`, probe
`steps`, observations, lost fields, policy markers and notes. CLI steps capture
phase, command, exit code and output; IDE steps capture phase, action, outcome
and output. The phases are install, reload, invoke, remove and verify.

IDE evidence distinguishes `pending`, `measured`, `owner-attestation` and
`owner-derived`, with source references and exact `derivedFrom` cell paths.
Owner policy definitions may have null version/OS, `not-measured` observations
and no empirical steps; they establish a policy restriction, not a measured host
capability. Derived file-mode assessments cannot exceed their matching source's
state, observations or losses; supported derivations require a measured supported
source. Policy markers name public settings;
directory presence, authentication failure or an empty marker list cannot
establish policy or an on-disk detector.

`supported` requires invocation and no demonstrated field loss. Discovery-only
results remain `partial`; an empty `lostFields` does not prove fidelity. Preserve the
[recorded semantic uncertainty](../parity/evidence-format.md).
Evidence for one role cannot establish invocation of another role. Undefined mode/scope
pairs remain `unverified`.

Raw evidence is **write-once**: never edit, replace, normalize or reformat a
snapshot. Add a new snapshot for a new run and append its SHA-256 and relative
path to the digest index. Integrity checks reject changed, missing or unindexed
snapshots. Keep the archived supplied probe script byte-for-byte; only the
maintained driver is used for new probes. Offline driver tests establish no new
host evidence or retroactive certification of historical cleanup claims.

Refresh only affected cells after a host major/minor version change, an adapter
change or expiry, whichever comes first. `recheckBy` is after `checkedOn` and at
most six calendar months later. Expired evidence never certifies a cell;
`unverified` never certifies support or satisfies strict policy.

Adapter tiers are `verified`, `community` and `unverified`. A verified tier
requires current evidence for the cells it claims; neither a tier nor another
cell's success upgrades a cell state or grants policy permission. Tier belongs
to adapter qualification, not an invented field in historical evidence records.

## Consequences

- Parity reports expose loss and uncertainty without broadening activation.
- [ADR 0010](./0010-adapters-and-delivery-modes.md) uses cell evidence for adapter
  support and delivery planning.
- [ADR 0011](./0011-manifest-provenance-locks-artifacts-trust.md) defines the
  artifact and policy inputs to projection, independently of runtime choices.
