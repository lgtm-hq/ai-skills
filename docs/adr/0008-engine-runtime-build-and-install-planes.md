# ADR 0008: Engine runtime: Python build plane, TypeScript install plane

- Status: Proposed (#562 native TypeScript Windows diagnostic measurement pending)
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

### Inspected R11 evidence and decision application

The report retains historical runs and now inspects the green
[PR run 41322684015](https://github.com/lgtm-hq/ai-skills/actions/runs/41322684015)
at exact clean source **196cb20a25a669498e5b6338bb633b7b11434e54**. Its twelve
unique schema-3 results (ten native plus two dedicated offline) have matching
source/expected head, empty source status, exact event/run identity and attempt 1.
The report links immutable artifacts, current footprint and raw commands.
[Dispatch 41323324901](https://github.com/lgtm-hq/ai-skills/actions/runs/41323324901)
was in progress at this revision's single status read; no green result is claimed.

- Private-registry installs pass with **both Bun and npm** and `--ignore-scripts`
  on all five targets; transported bytes, platform selection, golden execution
  and owned-server cleanup pass. No-Node passes everywhere.
- Both variants pass original direct execution plus npm local-file fallback
  under shared Linux namespaces and macOS sandboxes on all four POSIX targets.
- Windows **B passes offline**: exact direct and npm-installed interpreter
  controls are connected before rules, WinError 10013 during rules, with matching
  paths/hashes. Exact npm Node similarly reports EACCES; launcher identity matches
  and exact rule removal succeeds. A's direct and installed controls instead
  report **ECONNREFUSED/inconclusive**, despite matching paths/hashes. A executes
  successfully, but its offline status is still **unverified**. Refusal cannot be
  relabeled as access denial, and B's proof cannot establish A's proof.
- Unsigned security results remain within the answered owner scope: Mac quarantine
  readback succeeds, both variants fail assessment and marked CLI execution passes;
  Windows MotW readback and Defender custom scans pass, both entries are NotSigned,
  real-time protection is disabled and shell/SmartScreen enforcement is U. The
  report records signing/notarization needs; no paid gate is added.
- Dedicated Harden Runner has no same-host unrestricted baseline; its denial stays
  U. Payload provenance, fleet enforcement and deliberate deep-path behavior stay
  U. These are explicit limits, not universal-green gates on this comparison.

### Decision rule and minimal pending measurement

The **Python-first tie interpretation** follows the
[merged ADR escape hatch](https://github.com/lgtm-hq/ai-skills/blob/032ee309817813a9ef81bb2450cbed646a625222/docs/adr/0008-engine-runtime-build-and-install-planes.md),
which says to revise to a single Python engine behind a thin TypeScript npm
launcher if B is as deployable under the same private-registry, no-Node and
offline restrictions. This precedence is not an additional owner statement.
Otherwise accept A only if A is no worse on every required restricted criterion
across the supported targets. No size/file-count/timing budget is specified;
A's smaller POSIX footprint and B's smaller Windows footprint do not override it.

R11 proves registry/no-Node equality and POSIX offline equality, plus B's Windows
pass. A's Windows offline comparison is still unknown, so neither decision branch
is justified across all five targets. This is an observable diagnostic gap, not
an unanswered owner question or additional signing/provenance/fleet gate.

R12 minimally repairs only Bun Win64's diagnostic: the same compiled executable
and its npm-installed copy call native Winsock through deferred `bun:ffi`, retain
WSAGetLastError/SO_ERROR, and classify only connection access denial (10013) as
explicit denial. Nonblocking connect/select is bounded to two seconds. Cleanup
attempts socket close, WSACleanup and DLL close; errors invalidate proof and remain
structured raw evidence. npm's Node diagnostic and non-Windows paths are unchanged.
Injectable tests use no network and cannot establish native Windows proof.

**ADR 0008 and its index remain Proposed until fresh hosted evidence validates
this changed executable.** R11 is not evidence for R12 code or footprint. Parent
must inspect a new-head native matrix and genuine green dispatch, including all
12 results each and exact same-path/hash Windows direct/npm controls, actual npm
Node identity, golden execution and exact cleanup. Then apply the escape hatch
and update ADR/index/spike README together. An unknown must remain unknown.
Documentation-only follow-ups can cite proven unchanged executable source without
an endless rerun; this executable revision does not qualify for that exception.

Before implementation, reconcile #566/#567/#578/#386 with the selected runtime.
No downstream specification or production runtime is changed here; required #562
acceptance remains here and optional M5 NITs stay in #614.
