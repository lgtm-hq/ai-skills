# Architecture decision records

Architecture decisions for this repo, covering the plugin-canonical
engine and the proposed engine v2 runtime split.

Each ADR records its status and date, with Context, Decision and
Consequences sections. Accepted decisions guide implementation; proposed
decisions remain subject to their stated follow-up. Engine v2 work is
tracked in epic [#596](https://github.com/lgtm-hq/ai-skills/issues/596).

ADR 0008 remains Proposed pending comparable restricted **direct-runtime** and
npm local-file evidence under #562's resolved owner policy. Inspected R6 PR/green
dispatch evidence applies only to `10205e3`; R7 native CI stopped before measuring,
and R8 has local verification only. Bun local-file failure is informational;
registry still requires both clients. Signed Mac verification is tracked in #619,
not required to close #562. Windows scope, Harden Runner baseline and payload
provenance remain explicit measurement limits; see the ADR and distribution report.

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
