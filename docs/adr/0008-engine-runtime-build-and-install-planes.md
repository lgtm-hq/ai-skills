# ADR 0008: Engine runtime: Python build plane, TypeScript install plane

- Status: Proposed (#562 scenario and owner dispositions pending)
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
  no-Node, offline and required quarantine/security restrictions, revise this ADR
  to a single Python engine behind a thin TypeScript npm launcher.

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

The throwaway prototypes and collector live under
`research/install-plane-spike/`; the distribution report in
`docs/research/install-plane-distribution.md` records methods, actual observations,
limitations and concrete remaining experiments.
The inspected R3 [PR run 41292001121](https://github.com/lgtm-hq/ai-skills/actions/runs/41292001121)
and genuine [workflow_dispatch run 41292078852](https://github.com/lgtm-hq/ai-skills/actions/runs/41292078852)
both completed successfully at `ca2db52669b8611a7d9cd24733c80572516ff94a`.
Each retains twelve result JSONs in six evidence artifacts: ten native plus two
dedicated Linux offline observations. All 24 record matching source/expected
heads, clean status and exact event/run identity. The report links both artifact
lists, exact R3 footprint and security outputs. Dispatch collection acceptance is
met; collection success does not establish scenario acceptance or validate R4.

Registry clients and no-Node execution pass for both variants on all five targets.
Local-file Bun installs select all five platform packages while npm selects only
its target, both before and during restriction. Equal failures do not establish
deployability. Windows R3 now creates normalized per-program rules, observes
bundled Python IPv4 denial, runs both installers and verifies rule removal.
It has no same-program control for Bun, Node or installed runtimes: schema-2
`denial_proven=true` covers the Python probe only. Windows installer denial remains
unverified; R4 separates probe and installer proof without rewriting historical
JSON. POSIX shared namespace/sandbox proof remains valid. Windows registry tree
shutdown records graceful taskkill exit 255, forced exit 0 and parent reap,
not enumerated descendant absence; R4 reports that limitation as unverified.
Dedicated Harden Runner denial still lacks a same-host baseline.

R4 requires clean, matching expected source identity in hosted collection and
records the run attempt. Downloaded payload/build identity remains explicitly
unverified: archive hashes alone do not bind payloads to the expected source.

The existing escape hatch names these decision-bearing restrictions, evaluated
for **both variants on all five supported targets**:

- **Private registry:** Bun and npm separately install the wrapper and correct
  optional platform payload with `--ignore-scripts`, without a bootstrap, public
  registry dependency or uplink; transported bytes and execution are checked.
- **No Node:** the installed native payload executes with Node/Bun directories
  removed from PATH and no consumer Python/uv/pip/runtime fetch.
- **Offline:** Bun and npm separately install the same local tarballs using fresh
  caches and identical flags, with verified egress denial, then execute verified
  payloads. A network-unrestricted control with identical `--offline` flags
  distinguishes package-manager
  selection failures from failures introduced by the restriction. Both count as
  observations; a failed control never turns a restricted failure into a pass.
- **Quarantine and required security:** compare observed signing, assessment,
  marked-file execution and endpoint restrictions for both variants. R3 macOS
  assessment rejects both; A's signatures fail verification, B arm64 verifies
  ad hoc but is rejected, and B x64 is unsigned. Windows artifacts are unsigned;
  clean custom scans with real-time protection disabled do not establish fleet
  approval. Required signing/notarization and security routes need owner
  disposition and appropriate evidence.

Footprint (payload/archive bytes, file count, fresh-process timing and observed
cache writes) records deployment costs and tradeoffs. The issue supplies no size
or timing budget, so numeric differences alone do not establish a restricted
criterion failure or override its Python-first tie rule. An actual cache or
capacity restriction affecting installation/execution belongs to the corresponding
core observation. Any new owner budget must be stated before applying it; this
revision neither invents a threshold nor claims owner acceptance of an outcome.

Apply the documented Python-first rule only after inspecting complete comparable
evidence for every restricted criterion, including quarantine and required
security: revise to the Python escape hatch if B is equally deployable;
otherwise accept A only if it is no worse on **every** target/client/security
criterion. Unknown cells establish neither equality nor superiority. Known failures
need an explicit disposition against the owner's deployment requirements; identical
failures do not prove either variant deployable. If neither branch is supported,
retain Proposed and identify the missing experiment or unresolved requirement.

Third-party EDR, Finder/SmartScreen enforcement, disabled/unavailable Gatekeeper,
and the empty-allowlist job without an unrestricted baseline are **separately
unverified limitations**, never equal or pass. Report observed quarantine CLI
execution separately from security enforcement and signing requirements. These
limitations cannot supply missing core evidence, nor can the core comparison
establish fleet security approval or bypass required security. Observed quarantine
and signing differences are part of the every-criterion comparison above, even
when registry/no-Node/offline results pass. Owner requirements remain outstanding.

Independent namespace/sandbox/firewall denial is **not Harden Runner-only offline
proof**. The issue specifically requests empty-allowlist Harden Runner evidence;
the current dedicated job has no same-host baseline and remains unverified.
That methodological gap must stay explicit until a valid experiment establishes
it or the owner explicitly disposes of the unmet criterion. No such acceptance
is claimed here.

Proposed remains until fresh hosted JSON for every supported target/client has
been inspected, a true green **workflow_dispatch** run at the reviewed ref and raw
evidence are linked, and owner criteria permit applying the rule above. A green
collection job may contain truthful scenario failures. PR-triggered collection
cannot satisfy dispatch acceptance. Dispatch is already possible; inspected final
status and artifacts, rather than registration assumptions, establish that gate.
Update this ADR and its index together
only when the evidence supports a decision, then reconcile #566/#567/#578/#386.
No production runtime changes in this spike.
