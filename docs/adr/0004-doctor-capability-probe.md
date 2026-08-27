# ADR 0004: Doctor: implicit cached probe; explicit report / repair / migrate

- Status: Accepted
- Date: 2026-08-27
- Evidence: [plugin-engine-lab DECISIONS.md][lab-decisions]
  (Final Agreements item 4; explode vs native findings; lock↔disk #367)

## Context

Claude Code, Cursor, and Copilot can load plugins natively. Other hosts
may only see exploded skill dirs. Explode is strictly worse where plugins
work: no namespacing, no per-plugin disable, collisions at vendor scale,
and double-delivery when hosts read each other's skill directories
(Cursor reads `~/.claude/skills` and `~/.agents/skills`).

The current gateway also trusted lock files that did not match disk
(issue #367): "46 skills installed" with zero files. Capability and
install-state are both doctor concerns.

Users should not be asked the same host question on every install.

## Decision

**Implicit probe at install.** Detect whether a host can load plugins,
cache the result per host, and invalidate on host version change.
Ambiguity asks once and persists. On hosts with native plugin support,
prefer native unconditionally; explode is the fallback, not a toggle for
capable hosts.

**Explicit `sk doctor`** is report + repair + migrate:

- Report: host capability cache and lock↔disk reconciliation (existence
  and hash). Missing lock entries are not-installed / repairable, not
  silent success.
- Repair: restore lock↔disk agreement without changing projector.
- `--migrate`: deliberate projector cutover when a host's capability
  changes (probe / override / explicit-migrate, mirroring PwC DC-4444).

Smoke ritual for the doctor lives with the engine work (issue #376), not
in this ADR.

## Consequences

- Install path never offers explode on a host the probe marked native.
- Cross-host skill-dir reads must be in the host map so explode does not
  double-deliver (shared root or skip the overlapping host).
- Changelog migration for people is still wipe-and-reinstall
  ([ADR 0001](./0001-plugin-canonical-atomic-selection.md)); doctor
  migrate is projector cutover on one machine, not a catalog rewrite.

[lab-decisions]: https://github.com/lgtm-hq/plugin-engine-lab/blob/main/DECISIONS.md
