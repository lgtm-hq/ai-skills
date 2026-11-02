# Architecture decision records

Architecture decisions for this repo, covering the capability engine,
its generated host envelopes and the engine v2 runtime boundary.

Each ADR records its status and date, with Context, Decision and
Consequences sections. Accepted decisions guide implementation; proposed
decisions remain subject to their stated follow-up. Engine v2 work is
tracked in epic [#596](https://github.com/lgtm-hq/ai-skills/issues/596).

ADR 0008 applies #562’s measured Python-first escape hatch: one bundled Python
engine owns build and install behavior; strict TypeScript is the thin npm launcher.
See the
[distribution report](../research/install-plane-distribution.md)
for the five-target comparison, exact evidence identities and unverified limits.

| ID                                                          | Title                                                             | Status                        |
| ----------------------------------------------------------- | ----------------------------------------------------------------- | ----------------------------- |
| [0001](./0001-plugin-canonical-atomic-selection.md)         | Package publication and selection; atomic installation per plan   | Accepted (amended 2026-11-01) |
| [0002](./0002-neutral-metadata-generated-adapters.md)       | Neutral canonical metadata; host manifests are generated adapters | Accepted                      |
| [0003](./0003-upstream-native-slicing.md)                   | Upstream-native slicing over physical restructure                 | Accepted                      |
| [0004](./0004-doctor-capability-probe.md)                   | Doctor probes capability; policy chooses delivery mode and scope  | Accepted (amended 2026-11-01) |
| [0005](./0005-collision-doctrine.md)                        | Qualified identity, persistent aliases and explicit conflicts     | Accepted (amended 2026-11-01) |
| [0006](./0006-vendor-bake-safety.md)                        | Vendor bake safety: no execute, path rejection, coverage reports  | Accepted                      |
| [0007](./0007-publish-time-vendor-bake.md)                  | Vendor bake output is a publish-time artifact, not repo content   | Accepted                      |
| [0008](./0008-engine-runtime-build-and-install-planes.md)   | Engine runtime: bundled Python engine, thin TypeScript launcher   | Accepted                      |
| [0009](./0009-capabilities-and-parity.md)                   | Capabilities, dialects and parity                                 | Accepted                      |
| [0010](./0010-adapters-and-delivery-modes.md)               | Adapters, delivery modes and recovery                             | Accepted                      |
| [0011](./0011-manifest-provenance-locks-artifacts-trust.md) | Manifest, provenance, locks, artifacts, transports and trust      | Accepted                      |
