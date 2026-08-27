# Architecture decision records

Settled plugin-canonical decisions for this repo. Ported from the
[plugin-engine-lab evidence log][lab-decisions] (including the Final
Agreements section) so the *why* lives in-tree, not only in a throwaway lab.

Each ADR is accepted and short: Context, Decision, Consequences. One page
each. Implementation issues in epic
[#381](https://github.com/lgtm-hq/ai-skills/issues/381) execute these; they
do not re-open them.

| ID | Title | Status |
| --- | --- | --- |
| [0001](./0001-plugin-canonical-atomic-selection.md) | Plugin as the canonical artifact; atomic plugin-only selection | Accepted |
| [0002](./0002-neutral-metadata-generated-adapters.md) | Neutral canonical metadata; host manifests are generated adapters | Accepted |
| [0003](./0003-upstream-native-slicing.md) | Upstream-native slicing over physical restructure | Accepted |
| [0004](./0004-doctor-capability-probe.md) | Doctor: implicit cached probe; explicit report / repair / migrate | Accepted |
| [0005](./0005-collision-doctrine.md) | Collision doctrine: hash, registry rename, CI report, install line | Accepted |
| [0006](./0006-vendor-bake-safety.md) | Vendor bake safety: no execute, path rejection, coverage reports | Accepted |

[lab-decisions]: https://github.com/lgtm-hq/plugin-engine-lab/blob/main/DECISIONS.md
