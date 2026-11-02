# Engine glossary

Use one canonical term per concept. Each entry declares retired aliases with
`Replaces:`; `none` means no retired alias. Plural aliases are listed explicitly.
Literal source names in code are preserved. The contracts are
[ADR 0009](adr/0009-capabilities-and-parity.md),
[ADR 0010](adr/0010-adapters-and-delivery-modes.md) and
[ADR 0011](adr/0011-manifest-provenance-locks-artifacts-trust.md).

## catalog

A collection of published packages and their metadata, including declared vendor
imports and exports.

Replaces: none.

## package

The unit of publication and default selection, containing capabilities and their
resources. A package is independent of its generated host envelopes.

Replaces: bundle, bundles.

## capability

A qualified, stable identity with a role, source dialect, payload, dependencies
and provenance. It is the selectable behavior within a package.

Replaces: component, components.

## resource

A file or other payload input required by a capability, retaining lineage when
copied or shared.

Replaces: none.

## plugin

A generated host envelope, used only as output from a resolved, filtered
artifact. It is not a canonical publication or selection unit.

Replaces: none.

## role

The semantic kind of a capability: `skill`, `instruction`, `specialist`,
`workflow`, `lifecycle` or `integration`. It defines what the payload means.

Replaces: none.

## dialect

The source syntax and conventions of a capability, recorded separately from its
role. Sharing a dialect does not establish semantic equivalence.

Replaces: none.

## host

The destination product and interface that loads capabilities. Versions and OS
qualify evidence; a CLI and an IDE are distinct interfaces of a product.

Replaces: none.

## adapter

A registered implementation of host support reporting, planning, operations,
verification and recovery. It projects capabilities to a destination.

Replaces: none.

## artifact

The deterministic tarball and index containing resolved capabilities, resources,
closures and lineage, identified by digests and usable across transports.

Replaces: none.

## mode

The delivery form: `native-plugin`, `user-explode` or `repo-materialize`. Mode is
separate from the destination scope and subject to policy.

Replaces: none.

## scope

The explicitly requested destination boundary, such as user or project. A host
route must honor that boundary rather than silently substituting another one.

Replaces: none.

## vendor

A publisher supplying pinned imports to a consumer, with or without its own
manifest. Its declarations do not confer consumer trust.

Replaces: none.

## consumer

A repository or individual selecting and installing packages under its own
manifest or consumer profile and policy.

Replaces: none.

## re-exporter

An intermediate publisher explicitly exporting imported capabilities or resources
while preserving their origin and lineage.

Replaces: none.

## origin

The original publisher identity recorded in provenance, distinct from
intermediate publishers and current transport location.

Replaces: none.

## lineage

The authenticated declaration of derivation through intermediate publishers and
resource copies, including known inputs. It is not an authorship detector.

Replaces: none.

## provenance

The authenticated declaration of a capability's origin and intermediate
publishers, together with the lineage of its resources.

Replaces: none.

## lock

The committed deterministic `ai-skills.lock` record of resolved revisions,
digests, lineage, filters, closures and schema/builder versions.

Replaces: none.

## receipt

A machine-local record of installation ownership, hashes, aliases, scope and
adapter/policy fingerprints, used with a durable journal for recovery.

Replaces: none.

## policy

Consumer constraints on selection, delivery, execution, evidence and transports.
Vendor declarations cannot loosen these constraints.

Replaces: none.

## trust grant

An explicit execution authorization bound to a capability, origin, digest,
command, endpoint and event, invalidated by new execution surface.

Replaces: none.

## evidence

A dated, scoped record of probe steps, observations, losses and limitations, or
an explicitly sourced owner attestation/derivation. Raw snapshots are immutable;
offline tests do not establish new host behavior.

Replaces: none.

## tier

Adapter qualification: `verified`, `community` or `unverified`. It does not
replace a cell's evidence, state or policy assessment.

Replaces: none.

## parity cell

A host product/interface × version × OS × scope × mode × role assessment.
Policy-specific evidence is retained separately from the underlying identity.

Replaces: none.

## cell state

The assessed parity outcome: `supported`, `partial`, `unverified`,
`platform-unavailable`, `policy-blocked`, `source-unportable` or `adapter-missing`.
It is separate from adapter tier and constrained by evidence freshness.

Replaces: none.
