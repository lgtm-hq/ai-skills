# Architecture decision records

Architecture decisions for this repo, covering the plugin-canonical
engine and the proposed engine v2 runtime split.

Each ADR records its status and date, with Context, Decision and
Consequences sections. Accepted decisions guide implementation; proposed
decisions remain subject to their stated follow-up. Engine v2 work is
tracked in epic [#596](https://github.com/lgtm-hq/ai-skills/issues/596).

ADR 0008 remains Proposed for #562's **corrected denial controls and comparable evidence**.
Inspected green R11 PR [41322684015](https://github.com/lgtm-hq/ai-skills/actions/runs/41322684015)
applies to exact clean source `196cb20a25a669498e5b6338bb633b7b11434e54`: both
variants pass registry/no-Node on five targets. Linux's errno 101 was incorrectly
classified as denial and is inconclusive under R13; macOS records EPERM.
Windows Python records actual 10013; TypeScript executes successfully but
its matched controls return refusal/inconclusive. The new native Winsock diagnostic
and corrected Python/Node classifiers require fresh native/dispatch evidence,
with the Linux control limitation settled, before applying the merged escape hatch
and updating ADR/index/spike README together. Historical R11/R12 JSON and summaries
remain unchanged; their old classifiers cannot certify R13. Harden Runner's missing baseline,
independent payload
provenance and fleet enforcement stay explicit unknowns, not a universal-green
requirement. Bun local-file failure is informational; registry requires both
clients. Owner policy is answered: unsigned observations/documented signing needs
suffice; signed Mac verification is #619 and Authenticode is #618.

| ID                                                        | Title                                                              | Status   |
| --------------------------------------------------------- | ------------------------------------------------------------------ | -------- |
| [0001](./0001-plugin-canonical-atomic-selection.md)       | Plugin as the canonical artifact; atomic plugin-only selection     | Accepted |
| [0002](./0002-neutral-metadata-generated-adapters.md)     | Neutral canonical metadata; host manifests are generated adapters  | Accepted |
| [0003](./0003-upstream-native-slicing.md)                 | Upstream-native slicing over physical restructure                  | Accepted |
| [0004](./0004-doctor-capability-probe.md)                 | Doctor: implicit cached probe; explicit report / repair / migrate  | Accepted |
| [0005](./0005-collision-doctrine.md)                      | Collision doctrine: hash, registry rename, CI report, install line | Accepted |
| [0006](./0006-vendor-bake-safety.md)                      | Vendor bake safety: no execute, path rejection, coverage reports   | Accepted |
| [0007](./0007-publish-time-vendor-bake.md)                | Vendor bake output is a publish-time artifact, not repo content    | Accepted |
| [0008](./0008-engine-runtime-build-and-install-planes.md) | Engine runtime: Python build plane, TypeScript install plane       | Proposed |
