# ADR 0008: Engine runtime: Python build plane, TypeScript install plane

- Status: Proposed (#562 matched Windows executable controls pending)
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

### Inspected R10 evidence and decision application

The report preserves R3–R9 history separately. Current inspected evidence is the
R10 [PR run 41315907240](https://github.com/lgtm-hq/ai-skills/actions/runs/41315907240)
and genuine green [workflow_dispatch run 41316038552](https://github.com/lgtm-hq/ai-skills/actions/runs/41316038552),
both at exact clean source **80f328cb263c36c505ae1113224b7b36c36f85f6**.
Each has twelve unique schema-3 results: ten native (five targets × two variants)
and two dedicated Linux offline observations. All 24 have matching source and
expected head, empty source status, exact event/run identity and attempt 1.
The report links exact artifacts and records R10 commands, unsigned assessment
outputs, footprint and recommendation. These results are not R9 measurements.

For both A and B in both runs:

- Private registry passes with **both Bun and npm**, exact platform selection,
  verified installed bytes/golden execution and owned-server cleanup on all five
  targets. No-Node passes everywhere.
- Linux x64/arm64 and macOS x64/arm64 pass independent original standalone
  execution plus npm local-file fallback under shared namespace/sandbox denial.
- Windows actually executes both transports successfully, but bundled-Python
  probe denial is true and installer denial false. Separately scoped Node and
  direct/installed runtime executables have no matched controls. Direct and
  overall offline remain **unverified**, not passes or proven equality.
- Dedicated first-step empty-allowlist Harden Runner executes both transports
  but lacks a same-host unrestricted baseline; its denial remains unverified.
  Native Linux namespace proof is not credited to Harden Runner.
- All 24 payload-source identity records are unverified: native source hashes
  lack independent verification and transferred archive hashes are not bound to
  expected source/build metadata. Collector identity does not establish payload
  provenance. No production attestation pipeline or fleet approval is claimed.
- Unsigned macOS assessments reject both variants; direct marked CLI execution
  succeeds. A's inherited/ad-hoc signature fails verification; B arm64 verifies
  ad-hoc, B x64 is unsigned. Windows MotW readback and Defender custom scans
  succeed; both entries are NotSigned, real-time protection is disabled, and
  shell/SmartScreen enforcement is unverified. The report documents each
  variant's signing/notarization needs. This meets the owner's unsigned evidence
  scope without inventing a paid signing or third-party EDR gate.

### Decision rule and specific remaining measurement

The issue's **Python-first tie rule** takes precedence when B is equally
deployable: revise to a single Python engine behind a thin TypeScript npm
launcher. Otherwise accept A only if A is no worse on every required restricted
criterion across the supported targets. Footprint records costs, not a new
threshold: no size/file-count or timing budget is specified. A is smaller on
POSIX; B is smaller on Windows. Those numbers do not override the tie rule.

R10 supports a tie for registry/no-Node everywhere and offline on four POSIX
targets. **The Windows offline comparison is still unproven**, so neither branch
of the rule is justified across all five targets. Two unknown outcomes do not
establish equal deployability. This is a missing runner-observable control, not
an unanswered owner policy question, a demand for every field to be green, or
an extra signing/provenance/fleet gate on #562. Runner-unobservable limits may
remain explicitly unverified as the issue permits; free production attestation
obligations remain binding before trusted distribution is claimed.

The minimal follow-up in this revision adds matched Windows program controls:
A's compiled diagnostic, B's existing interpreter probe, npm's explicitly selected
Node launcher, and exact future npm-installed payload paths. Baseline copies are
removed before fresh real installations. Connected-before/explicit-denial-after,
identical argv/executable path/SHA-256, actual npm launcher match and exact rule
cleanup are required. Offline tests inject socket/process boundaries and do not
supply native proof. Informational Bun local-file execution is outside this
required denial scope; its existing failure remains recorded.

**ADR 0008 and its index remain Proposed until fresh hosted results validate this
executable change.** R10 cannot certify the new controls. Inspect the new
native/dispatch JSON, apply the rule, and update ADR/index/spike README together.
Documentation-only edits may continue citing the exact executed source when
source/workflow/test/package hashes are unchanged; they do not require an endless
rerun of unchanged executables. This revision changes executable bytes, so that
exception does not apply.

Before future implementation, reconcile #566/#567/#578/#386 with whichever
runtime is selected. The local parent handoff records the pending Windows gate
and conditional implications; no downstream issue or remote metadata is changed
here. Optional M5 NITs stay #614. No production runtime changes in this spike.
