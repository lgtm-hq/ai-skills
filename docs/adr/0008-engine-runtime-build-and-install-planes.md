# ADR 0008: Engine runtime: Python build plane, TypeScript install plane

- Status: Proposed (#562 live distribution evidence pending)
- Date: 2026-11-01
- Scope: [#561](https://github.com/lgtm-hq/ai-skills/issues/561), part of
  [engine v2 (#596)](https://github.com/lgtm-hq/ai-skills/issues/596)

## Context

The gateway in `npm/ai-skills/lib/` and `bin/skill.js` is authored
JavaScript; `package.json` declares Node >=20 and Bun >=1.0.0. Bake,
registry, safe-tree checks, generators and re-pin live in Python under
`scripts/` and `scripts/vendor_registry/`, run with `uv` via `pyproject.toml`.
Engine v2 adds dependency closure, provenance, lineage and policy. Allowing
both runtimes to resolve would create two resolvers that can disagree.

Consumers may have only private npm mirrors, no Node, or offline machines.
The runtime boundary must support those restrictions without requiring
consumer Python. Project standards allow Python, TypeScript and Rust;
authored JavaScript is disallowed. Deployment evidence belongs to
[#562](https://github.com/lgtm-hq/ai-skills/issues/562); this decision is
provisional until that spike concludes.

## Decision

- **Python build plane (`uv`).** Own source and version resolution, graph
  closure, provenance and lineage construction, build-time policy
  evaluation, bake and host manifest generation. Only authors and CI need
  Python under this split.
- **Artifact contract.** Embed complete capability and resource inventories,
  precomputed transitive closure for each capability, and lineage. Bind all
  of it to a verified artifact digest. A published JSON Schema and shared
  golden fixtures (identical inputs and expected outputs in pytest and
  `bun test`) define the boundary.
- **TypeScript install plane (strict, Bun toolchain).** Verify the digest;
  subtract packages and capabilities by set membership in embedded data;
  then reject any retained closure containing a removed item. Enforce
  consumer and org denies by origin anywhere in the provenance chain,
  across any number of hops, plus trust and support policy, from that
  metadata alone. Regenerate filtered host envelopes deterministically,
  plan and apply destination-adapter operations, and write receipts.
  **The install plane never resolves** new sources, versions or
  dependencies. This is a testable boundary: missing closure or lineage
  data, or a policy it cannot evaluate, must fail closed rather than
  trigger resolution or fetch missing inputs.
- **Distribution.** Ship an npm package compatible with private registry
  mirrors and per-platform `bun build --compile` binaries for machines
  without Node. No install-time network bootstrap is permitted. These are
  provisional delivery choices for #562 to validate under the same
  restrictions, including offline use.
- **Language rule.** JavaScript emitted from TypeScript, including JS
  embedded in compiled binaries, is acceptable. Remove authored `.js` in
  [#566](https://github.com/lgtm-hq/ai-skills/issues/566).
- **Rust.** Do not adopt it. Only a superseding ADR may reopen Rust if the
  install plane starts needing resolution logic, which this ADR forbids.
- **Escape hatch.** If #562 finds that a bundled Python runtime is as
  deployable as the compiled binary under the same private-registry,
  no-Node and offline restrictions, revise this ADR to a single Python
  engine behind a thin TypeScript npm launcher.

## Consequences

- There is one resolver. Consumers filter resolved artifacts and fail
  closed when their embedded metadata cannot support an install.
- [#566](https://github.com/lgtm-hq/ai-skills/issues/566) migrates the
  authored gateway to strict TypeScript;
  [#567](https://github.com/lgtm-hq/ai-skills/issues/567) extracts the build
  plane into an importable, typed Python engine package.
- Follow-up CI gates are `bunx tsc --noEmit`, `bun test` and `uv run pytest`.
  Both test suites run the shared golden fixtures to prove the contract,
  closure checks, deny propagation and fail-closed boundary agree.
- #562 finalizes or revises this proposal using distribution evidence.
  Host evidence follows in
  [#563](https://github.com/lgtm-hq/ai-skills/issues/563); this ADR runs
  neither spike and changes no runtime behavior.

## Distribution evidence gate (#562)

The throwaway prototypes and collector now live under
`research/install-plane-spike/`; method, local Linux observations, limitations and
the remaining acceptance criteria are recorded in
`docs/research/install-plane-distribution.md`. Local results establish neither
macOS nor Windows deployability. The hosted multi-OS workflow has not yet run.

This status stays Proposed until the parent records live per-scenario evidence
and its green collection-run link, then applies the decision rule. Evaluate the
Python escape hatch first when measured deployability is equal; otherwise accept
TypeScript only if it is no worse on every restricted criterion. Unknown security
or platform results do not count as equality or superiority. If neither result is
supported, retain Proposed and identify the missing experiment. The ADR index must
change with any final status revision. No production runtime changes in this spike.
