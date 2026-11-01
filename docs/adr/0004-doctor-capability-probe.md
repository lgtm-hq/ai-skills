# ADR 0004: Doctor probes capability; policy chooses delivery mode and scope

- Status: Accepted (amended 2026-11-01)
- Date: 2026-08-27
- Amends: Separate capability probing from policy; require explicit delivery
  mode and scope while retaining cached probe, report, repair and migrate.
- Evidence: [plugin-engine-lab DECISIONS.md][lab-decisions]
  (historical delivery and install-state findings; Final Agreements item 4)

## Context

Hosts differ in what they can load and where they can install content.
A policy-restricted host may support native plugins while local plugin
import is disabled. Capability alone cannot authorize a delivery mode.
Implicit scope can also put a requested project install into a user's
global configuration, and overlapping host directories can double-deliver
content.

Recorded install state can disagree with disk. Doctor must expose both
capability and install-state problems without asking the same host
question on every install.

## Decision

**Implicit probe at install.** Report what a host can do separately from
detected policy markers, such as local plugin import being disabled.
Cache capability results per host and invalidate on host version change.
Ambiguity asks once and persists; a capability answer never grants policy
permission.

**Policy chooses delivery.** Org policy selects the mode per host:
`native-plugin`, `user-explode` or `repo-materialize`, and the allowed
roles, vendors and transports. The probe never raises the mode above
policy. Choose native delivery only when policy allows it and the host
can accept the resolved, filtered artifact as a generated plugin envelope.

**Scope is explicit.** A destination adapter honors the requested scope
or rejects the plan. It must not silently substitute user scope for
project scope. Mode and scope apply to the selected capabilities and
resources of a package, not to an unfiltered upstream tree.

**Explicit `sk doctor`** is report + repair + migrate:

- Report: capability cache, detected policy markers, chosen mode and
  scope, plus recorded-state↔disk reconciliation (existence and hash).
  Missing recorded files are not-installed / repairable, not silent success.
- Repair: restore recorded-state↔disk agreement without changing mode,
  scope or destination adapter.
- `--migrate`: deliberate delivery cutover when capability or policy
  changes, subject to the same policy and scope validation.

## Consequences

- [#582](https://github.com/lgtm-hq/ai-skills/issues/582) implements org
  policy independently of capability probing.
- [#581](https://github.com/lgtm-hq/ai-skills/issues/581) implements
  delivery modes and explicit scope through destination adapters;
  adapters must account for overlapping host directories.
- [#586](https://github.com/lgtm-hq/ai-skills/issues/586) provides v1-to-v2
  install and registry migration, distinct from doctor delivery cutover
  ([ADR 0001](./0001-plugin-canonical-atomic-selection.md)).
- [#565](https://github.com/lgtm-hq/ai-skills/issues/565) defines adapter
  contracts and host-specific mode/scope details using the host evidence
  from [#563](https://github.com/lgtm-hq/ai-skills/issues/563).

[lab-decisions]: https://github.com/lgtm-hq/plugin-engine-lab/blob/main/DECISIONS.md
