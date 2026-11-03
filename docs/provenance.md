# Provenance and lineage

The engine records declared origin chains for capabilities and resources. Hop zero
is the origin; the last hop is the current publisher. Local, uncommitted payloads
use a null revision. Imported publications use the consumer's exact SHA pin.
Publisher short names never authorize origin denies: denies match origin locators
at every depth, including required resource chains. Renames, frontmatter rewrites,
explicit migrations and resource copies retain earlier hops. A denied shared
resource invalidates every kept capability that requires it.

Provenance is an authenticated declaration, not a detector of copying. An imported
`ai-skills.lineage.json` index is an array of records governed by
[`schema/lineage.v1.schema.json`](../schema/lineage.v1.schema.json). The engine checks
its last origin and revision against the import pin and binds its last path and
tree digest to observed bytes. Caller-supplied offline snapshots still receive a
pin-unverified warning: a claimed revision does not authenticate those bytes.
The schema ships in the engine wheel; ingestion never relies on the caller's
working directory. `plan --json` embeds each record's ordered chains and claims;
text plans print all hops. Multiple chains retain the union of known ancestry.
Denies run before any subsequent content deduplication.

Manifest vendors resolve their own imports recursively at their declared pins.
Only explicit package exports carry nested imports to a consumer. For offline
planning, supply direct snapshots with `--vendor-root y=PATH` and nested snapshots
with `--vendor-root y/x=PATH`. Missing recursive inputs remain visible and fail
strict provenance. Re-export cycles and excessive nesting fail closed. Acquisition
requires the existing explicit inventory fetch option; planning never fetches or
executes vendor code. Vendor policy and trust overrides never loosen the final
consumer's policy. Publisher-local migrations and authorship claims are descriptive
metadata, subject to the consumer's vetoes.

For each shipped payload file, the engine compares SHA-256 with every file in that
publisher's own declared pinned input trees, including files outside import
filters. Byte equality without the corresponding origin and revision raises
`provenance.missing-lineage`. This proves byte equality, not authorship, and does
not invent ancestry. `policy.provenance.mode: warn` reports warnings; `strict`
reports errors, including `provenance.unverifiable-lineage` for unbound indexes.
This catalog declares strict mode.

An independently authored claim uses
`overrides.attestations: [{capability, path, independentlyAuthored: true, reason}]`.
The path names a file relative to that capability's payload. Claims travel with
published chains. Only the final consumer's
`policy.provenance.acceptAttestations: true` can clear missing-lineage failures.
Claims against known imported ancestry or consumer origin denies are rejected as
`provenance.attestation-conflicts-lineage`; they never erase recorded ancestry.

Nothing beyond the publisher's declared inputs is checked. Concealed or hand-copied
content from undeclared inputs is not detected. An independent publisher that does
not import X gains no X ancestry or diagnostic merely by shipping identical bytes.
The lineage declaration also cannot establish license ownership or originality;
license and notice obligations still apply through imports and re-exports.
