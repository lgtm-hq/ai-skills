# ADR 0001: Package publication and selection; atomic installation per plan

- Status: Accepted (amended 2026-11-01)
- Date: 2026-08-27
- Amends: Package selection replaces plugin-only selection; dependency-aware
  filtering and atomic installation are separate decisions.
- Evidence: [plugin-engine-lab DECISIONS.md][lab-decisions]
  (historical atomic-install findings; Final Agreements item 3)

## Context

Copying individual directories without their dependencies or resources
can leave partial trees and untracked content. Atomic installation avoids
that failure, but does not require selecting every capability in a package.

Consumers need declarative selection, including exclusions for content
re-exported by another vendor. Host envelopes vary with delivery mode and
scope; making one host's plugin format the publication model prevents
policy-restricted hosts from consuming the same resolved artifact.

## Decision

A **package** is the unit of publication and the default unit of selection.
It contains capabilities and their resources. A **plugin** is only a
generated host envelope: an output derived from the resolved, filtered
artifact, never the canonical authoring or selection unit.

A manifest may narrow selection with declarative `include` / `exclude`
selectors over qualified capability IDs:

- Absent `include` selects all capabilities; `include: []` selects none.
- Includes expand the transitive `requires` closure and resource closure.
- Excludes and org denies always win, matching origin anywhere in the
  provenance chain. A retained dependency on excluded or denied content
  fails the plan with the dependency chain.
- Every explicit selector must match; unmatched selectors fail the plan.

This amendment supersedes only the plugin-only selection consequence
of [ADR 0003](./0003-upstream-native-slicing.md), including its requirement
that individual skills join a plugin or remain unavailable. The package
default and capability `include` / `exclude` rules above apply instead.
ADR 0003's canonical `skills/` authoring layout, upstream-native slicing
and other decisions remain unchanged.

Installs and updates are atomic per plan. There is no interactive
cherry-pick cart. Runtime enable/disable is separate from selection.
Delivery mode is a policy choice; destination adapters honor the requested
scope or reject the plan ([ADR 0004](./0004-doctor-capability-probe.md)).

## Consequences

- [#570](https://github.com/lgtm-hq/ai-skills/issues/570) implements
  dependency-aware selection and selector drift failures.
- First-party and vendor packages use the same artifact contract;
  [ADR 0006](./0006-vendor-bake-safety.md) continues to govern bake safety.
- [#383](https://github.com/lgtm-hq/ai-skills/issues/383) implements lifecycle
  and integration roles under trust policy, separate from selection.
- [#586](https://github.com/lgtm-hq/ai-skills/issues/586) provides migration
  for existing installs and registries.
- [#565](https://github.com/lgtm-hq/ai-skills/issues/565) specifies the
  artifact and delivery mechanisms without changing these decisions.

[lab-decisions]: https://github.com/lgtm-hq/plugin-engine-lab/blob/main/DECISIONS.md
