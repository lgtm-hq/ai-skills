# ADR 0008: Engine runtime: Python build plane, TypeScript install plane

- Status: Proposed (#562 restricted direct-runtime measurements pending)
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

The report at `docs/research/install-plane-distribution.md` retains
historical observations and raw run links. The prototypes and collectors live in
`research/install-plane-spike/`, outside the published npm package.

### Binding owner policy (resolved)

The [security decision](https://github.com/lgtm-hq/ai-skills/issues/562#issuecomment-6557818942)
and [offline decision](https://github.com/lgtm-hq/ai-skills/issues/562#issuecomment-6557886641)
answer the earlier owner questions:

- The **standalone compiled binary is the primary offline transport**, with no
  install step. Compare B's self-contained directory bundle by the same direct
  execution test. An **npm-only local-file wrapper is the documented fallback**.
  Both direct execution and the npm fallback decide offline acceptance per target
  and variant. Bun local-file selection failures remain evidence, outside this
  gate; see the existing upstream [oven-sh/bun#47640](https://github.com/oven-sh/bun/issues/47640).
- **Registry installs still require both Bun and npm**, including private
  registries, correct optional platform selection and `--ignore-scripts`.
- #562 records unsigned quarantine, `spctl`, codesign, MotW, Defender and
  SmartScreen observations and each variant's signing/notarization requirements.
  A signed Mac run is **not required for #562**. Developer ID/notarization is the
  human-secret gate in [#619](https://github.com/lgtm-hq/ai-skills/issues/619);
  Authenticode is cost-gated in [#618](https://github.com/lgtm-hq/ai-skills/issues/618).
  No paid or third-party EDR experiment is required. The deliverable where paid
  signing is unavailable is unsigned but attested; free checksum, provenance,
  artifact/npm attestations and keyless signing obligations remain. This spike
  does not claim to have implemented the production attestation pipeline.

Earlier dual-client offline rollups are historical outcomes under the superseded
policy. Their raw JSON is unchanged. They are neither new-policy failures nor
proof of direct-runtime success. Owner policy is resolved; missing measurements
remain missing measurements.

### Inspected evidence and outstanding experiment

R3 (`ca2db52`), R4 (`d77da01`) and R5 (`6d2d86b`) run identities remain in the
report. The retained complete R6 [PR run 41303888697](https://github.com/lgtm-hq/ai-skills/actions/runs/41303888697)
and green [workflow_dispatch run 41304035426](https://github.com/lgtm-hq/ai-skills/actions/runs/41304035426)
apply **only to `10205e3519ab610c97fd2a846bfc54e9ecbe3048`**. Each has twelve
unique schema-3 scenario JSONs (ten native and two dedicated Linux offline),
matching source/expected heads, clean source, event/run identity and attempt 1.
Both variants pass registry (both clients, overall including owned-job cleanup)
and no-Node on all five targets. npm local-file installation/execution passes
before and during restriction; Bun's platform-selection failures are retained.
Linux/macOS prove shared namespace/sandbox denial. Windows proves only bundled
Python probe denial, not every installer/runtime program, and verifies rule removal.
Dedicated Harden Runner lacks a same-host unrestricted baseline. Payload/build
source binding remains unverified. No R6 document contains the independent
**original standalone payload executed under restriction, without installation**
cell needed by the owner's primary transport rule.

The actual R7 [PR run 41307370871](https://github.com/lgtm-hq/ai-skills/actions/runs/41307370871)
at `774ba560bcb0fdffa21b41c6e9127a11d26a02eb` failed all five native test jobs
before build/measurement because isolated tests lacked PyYAML. It supplies no
native scenario evidence. R8 corrects that isolated command, adds independent
restricted direct-runtime cells, and applies direct-plus-npm offline rollups;
Bun evidence is retained and registry requirements are unchanged. R8 has local
verification only. Earlier green runs cannot validate R8.

**Proposed remains for a measured criterion:** inspect fresh comparable hosted
JSON for the original standalone A and B payloads under restriction on all five
targets, plus npm local-file fallback, at the reviewed source. Windows program
rules alone cannot certify runtime/installer denial without matched same-program
positive/restricted controls. The first-step empty-allowlist Harden Runner job
still needs a valid same-host baseline, and transferred payload provenance must
be bound before claiming it verified. Keep these limitations explicit; namespace
or sandbox evidence is not Harden Runner-only proof. Link a genuine green dispatch
and inspect source/build identities when reconciling the new collector. No current
head hosted validation or final acceptance is claimed.

### Decision rule

Apply the issue's **Python-first tie rule** after comparable evidence supports
all restricted criteria: private registry (both clients), no Node, offline
(direct primary plus npm local-file fallback), and the owner-required unsigned
security observations and documented signing needs. Revise to a Python engine
behind a thin TypeScript npm launcher if B is equally deployable. Otherwise accept
A only if it is no worse on every restricted criterion on every supported target.
Unknown measurements prove neither equality nor superiority. Bun local-file
failure, unsigned assessment rejection, missing paid signing and third-party EDR
cannot be reintroduced as owner-policy blockers.

Footprint records costs, not a new threshold: #562 supplies no size/file-count or
timing budget. Numeric differences alone do not override the Python-first rule.
Finder/SmartScreen enforcement and real fleet policy remain separately unverified;
CLI execution and Defender custom scans do not establish those claims.

Complete comparable direct-offline measurements are still needed before either
branch of the rule is justified. Keep the ADR, index and spike README consistent,
then reconcile #566/#567/#578/#386 when evidence permits a final decision. Optional
M5 NITs stay on #614; measured acceptance remains on #562. This spike changes no
production runtime.
