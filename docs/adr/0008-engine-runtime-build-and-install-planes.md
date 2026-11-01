# ADR 0008: Engine runtime: bundled Python engine, thin TypeScript launcher

- Status: Accepted
- Date: 2026-11-01
- Scope: [#561](https://github.com/lgtm-hq/ai-skills/issues/561), finalized by
  [#562](https://github.com/lgtm-hq/ai-skills/issues/562), part of
  [engine v2 (#596)](https://github.com/lgtm-hq/ai-skills/issues/596)

## Context

The gateway in `npm/ai-skills/` is authored JavaScript, while resolution, bake,
registry and generators live in Python under `scripts/`. Engine v2 adds closure,
provenance, lineage and policy. Two implementations risk disagreement. Restricted
consumers may have only private npm mirrors, no Node, or no network; they must not
need a Python installation or toolchain.

The original proposal split Python build and TypeScript install planes. Its
[merged escape hatch](https://github.com/lgtm-hq/ai-skills/blob/032ee309817813a9ef81bb2450cbed646a625222/docs/adr/0008-engine-runtime-build-and-install-planes.md)
requires one Python engine behind a thin TypeScript npm launcher if bundled
Python is equally deployable under the same private-registry, no-Node and offline
restrictions. The [distribution report](https://github.com/lgtm-hq/ai-skills/blob/research/562-install-plane-spike/docs/research/install-plane-distribution.md)
now establishes that comparison on all five native targets.

## Decision

- **One typed Python engine owns both planes.** The build entry point owns
  source/version resolution, graph closure, provenance, lineage, policy, bake and
  host envelopes. The install entry point owns verification, subtractive filtering,
  deny evaluation, destination-adapter planning/application and receipts. Authors
  and CI use `uv`; consumers execute the distributed bundled runtime.
- **Preserve the build/install boundary.** Published artifacts embed complete
  capability/resource inventories, precomputed transitive closure and lineage,
  bound to a verified digest and defined by JSON Schema and golden fixtures.
  Install uses only that resolved metadata: it never resolves new sources,
  versions or dependency edges. Missing closure/lineage or an unevaluable policy
  fails closed before writes. Diagnostic walks of embedded edges do not resolve.
  Denies match origin anywhere in capability or resource ancestry across any
  number of re-export hops.
- **Thin strict TypeScript npm launcher.** Select and invoke the packaged Python
  payload; forward arguments, output, signals and exit status; handle launcher
  diagnostics. Do not implement another resolver, verifier, filter, policy
  evaluator or installer in TypeScript. Use Bun for development. Emitted JavaScript
  is permitted; authored `.js`/`.mjs`/`.cjs` is not.
- **Self-contained distribution.** Per-platform bundled Python directories include
  the interpreter and required engine dependencies. Direct execution requires no
  consumer Python, uv, pip, Node or Bun. npm uses the thin launcher and optional
  `os`/`cpu` payload packages, compatible with both Bun and npm, private mirrors
  and `--ignore-scripts`. No postinstall bootstrap, floating dependency or runtime
  download is allowed.
- **Offline transport.** Apply the owner's standalone-primary rule to the chosen
  bundled Python runtime: execute it directly with no install step. The npm-only
  local-file wrapper is the documented fallback. Both direct execution and npm
  fallback must pass per target. Bun local-file selection failure remains evidence
  outside this gate ([oven-sh/bun#47640](https://github.com/oven-sh/bun/issues/47640));
  both clients remain required for registry installs.
- **No Rust adoption.** Reopening the runtime or install-resolution boundary
  requires a superseding ADR.

## Evidence and applied rule

Green [PR run 41332673633](https://github.com/lgtm-hq/ai-skills/actions/runs/41332673633)
and genuine [dispatch 41332723822](https://github.com/lgtm-hq/ai-skills/actions/runs/41332723822)
execute exact clean source `fb4d21bbc68579606a283afa69af3eee664dab61`. All 24
unique schema-3 results were inspected (ten native plus two dedicated offline per
run), with matching source/expected head, empty status, exact event/run and
attempt 1. The report links every artifact and raw JSON digest.

Both variants pass registry installation with both clients, no-Node execution,
standalone offline execution and npm local-file fallback on Linux x64/arm64,
macOS x64/arm64 and Windows x64. Linux has connected IPv4 then connect EACCES/13
under shared namespace-only `prohibit` policy and verified cleanup; macOS records
EPERM in the shared sandbox. Windows matches exact direct/installed paths and
hashes before/during rules: native Winsock SO_ERROR 10013 for A, actual WinError
10013 for B, EACCES from npm's exact Node launcher, and verified rule removal.
Unreachable IPv6 is informational and supplies no denial proof.

**Apply the Python-first tie branch:** B is equally deployable under the required
restrictions, so accept this revised single-engine decision. No size, file-count
or timing threshold was specified. A's smaller POSIX footprint and B's smaller
Windows footprint do not override that rule. Unknowns remain unknown; equality
rests on the required native passes.

The report records the source diff proving prototype, collector, build and pin
bytes unchanged from `fb4d21b` through `7909883621f726eb26806f23ab075b91c6153064`
and this documentation/main integration. The intervening changes move tests and
change workflow triggers. Historical R11/R12 artifacts are never relabeled.
Dispatch 41335569949 belongs to `7909883`; collect its completion and results
separately rather than assigning it older JSON.

## Security policy and limits

The [owner security decision](https://github.com/lgtm-hq/ai-skills/issues/562#issuecomment-6557818942)
requires unsigned quarantine, `spctl`, codesign, MotW, Defender and SmartScreen
observations and documented signing needs. The report records commands and
outputs. CLI execution and clean custom scans are not fleet or shell approval.
Mac assessment fails; Windows entries are NotSigned with real-time Defender off.

Free SHA-256 checksums, GitHub artifact attestations, SLSA provenance, npm
provenance and Sigstore/cosign keyless signing remain production obligations.
Where paid signing is absent, delivery is **unsigned but attested**; this spike
does not implement or certify that release pipeline. Developer ID/notarization
is human-secret-gated [#619](https://github.com/lgtm-hq/ai-skills/issues/619);
Windows Authenticode is cost-gated [#618](https://github.com/lgtm-hq/ai-skills/issues/618).
No paid service or third-party EDR experiment is required for #562.

Dedicated first-step Harden Runner denial without a same-host baseline,
independent payload-to-source binding, Finder/SmartScreen enforcement, fleet
policy, deliberate long paths, disk-cold performance and read-only runtime limits
remain **unverified**. Native namespace proof is not Harden Runner proof. These
limits are explicit, not additional universal-green runtime-selection gates.

## Consequences

- [#566](https://github.com/lgtm-hq/ai-skills/issues/566) retains strict TypeScript,
  no authored JavaScript, CLI behavior parity and CI. Its final npm role is the
  thin launcher; Bun-compiled install engines are not the production plan.
- [#567](https://github.com/lgtm-hq/ai-skills/issues/567) extracts the importable
  typed Python engine as a behavior-preserving foundation for both planes.
  [#578](https://github.com/lgtm-hq/ai-skills/issues/578) implements verification,
  filtering, denies and consumer profiles there. The launcher delegates.
- [#386](https://github.com/lgtm-hq/ai-skills/issues/386) distributes the same
  attested artifacts and self-contained Python payloads through all transports,
  including private npm mirrors and direct offline payloads. The npm wrapper is
  the fallback; consumer Python is never a prerequisite.
- Retain `uv run pytest`, `bun test` and `bunx tsc --noEmit` CI gates. Shared
  fixtures verify contract semantics and launcher-to-engine behavior. Both spike
  prototypes remain research evidence outside the published npm `files` allowlist.
- This ADR changes the specification, not the production engine. Reconcile the
  four downstream issue bodies and implementation prompts before implementation,
  preserving unrelated criteria and owner policies. Optional spike hardening
  stays in #614 under the owner's review cap.
