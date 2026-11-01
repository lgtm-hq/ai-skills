# Install-plane distribution experiment (#562)

Date: 2026-11-01. **Evidence incomplete; ADR 0008 remains Proposed.** This is the
throwaway distribution experiment after #561/#613 (`032ee309`), not the M6 engine.
There has been no push, workflow dispatch, or GitHub mutation from this session.

## Method and scope

[Sources and reproduction](../../research/install-plane-spike/README.md) include:

- One generated, data-only USTAR fixture, two qualified capability IDs, file hashes,
  an archive hash, embedded closures, and golden output after excluding one ID.
- A strict TypeScript prototype, compiled using `bun build --compile` for native
  `darwin-arm64`, `darwin-x64`, `linux-x64`, `linux-arm64`, and `windows-x64` targets.
- A stdlib-only Python prototype bundled with the entire uv-managed
  python-build-standalone distribution as a relocatable directory. `uv python find
--managed-python` selects it; `uv python install` is CI setup only. The directory
  is carried in an archive, with no self-extractor, pip, uv or dependency fetch at
  execution. Python runs with `-I -B`. Symlinks are dereferenced because npm pack
  omits them. This increases size and file count; it is a conservative untrimmed
  baseline, not a minimum possible Python footprint. Runtime licenses and notices
  remain in the copied distribution; production redistribution needs its own audit.

Both runtimes verify tar/file digests and complete file inventories before writes,
filter by ID set membership, and reject missing/unknown/removed closure entries.
They perform no resolution, policy discovery, vendor execution or network access.
The index is **not authenticated** by this experiment: a co-located digest detects
corruption, not a maliciously replaced index and archive. Attestation, lineage,
schema evolution, journaling and production archive handling remain M6/M7 work.

The [dispatch workflow](../../.github/workflows/install-plane-spike.yml) builds and
runs natively on five hosted runner labels. Setup may fetch tools/runtimes; measured
offline workers use already acquired archives and bundled Python tooling. Each
scenario has full command/stdout/stderr/exit/timing JSON. Archive SHA-256 and dirty
checkout status identify local preview evidence; live evidence must name a clean,
committed source head and the workflow run URL.

## Current observations

Only local Linux x64 has been measured. Local versions: Bun 1.4.3, uv 0.13.1,
standalone CPython 3.14.7, Verdaccio 6.2.0. CI uses the repository's shared Bun/uv
pins, so its results must be assessed separately. The machine reports
Linux 7.0.0-42 with glibc 2.43. Nothing here establishes older Linux compatibility.

| Criterion                                           | A: compiled TypeScript, local Linux x64          | B: standalone Python directory, local Linux x64  |
| --------------------------------------------------- | ------------------------------------------------ | ------------------------------------------------ |
| Golden stdout and written tree                      | Pass                                             | Pass                                             |
| No Node/Bun on PATH                                 | Pass, PATH empty                                 | Pass, PATH empty                                 |
| Local-file install with egress denied               | Pass in `sudo -n unshare --net`                  | Pass in the same network namespace               |
| Default Verdaccio publication                       | Fail: HTTP 413 Payload Too Large                 | Fail: HTTP 413 Payload Too Large                 |
| Private registry, explicit 512 MB request allowance | Pass, ignore-scripts install + installed runtime | Pass, ignore-scripts install + installed runtime |
| Unpacked bytes / files                              | 90,812,917 / 4                                   | 207,917,967 / 4,966                              |
| Archive bytes                                       | 41,897,811                                       | 73,984,429                                       |
| Fresh process wall times, 3 samples (ms)            | 20.563, 22.017, 22.190                           | 141.109, 41.908, 42.230                          |
| HOME cache directory unavailable                    | Pass; no other HOME files observed               | Pass; no other HOME files observed               |
| Native quarantine / EDR                             | Unverified on Linux                              | Unverified on Linux                              |

The first namespace attempt failed with `write failed /proc/self/uid_map: Operation
not permitted`. The root network namespace worked. The negative controls returned
IPv4 `ENETUNREACH` and IPv6 `EADDRNOTAVAIL`, after which both local archives were
installed and executed. This local run did **not** use Harden Runner; the separate
empty-allowlist CI job remains unverified.

The default registry failure is material: registry request limits can prevent either
runtime from being mirrored. The second configuration raises the stand-in's limit
explicitly; success there does not prove deployment through a default or corporate
registry. The wrapper has optional platform dependencies but no lifecycle scripts
or npm launcher. Publication uses a disposable local account because Bun refuses
anonymous publication even when server policy permits it. Client installs use
`--ignore-scripts`, a new cache, explicit loopback registry and no Verdaccio uplinks.
There is no firewall around that client; the test shows registry configuration and
server fetch logs, not universal enforcement against a malicious package manager.

No-node means PATH removal as requested, not physical uninstallation. Fresh-process
times include fixture verification, writes and subprocess launch, with warm OS page
caches; they are not disk-cold measurements. The blocked `.cache` path and HOME
inventory constrain only observed HOME cache behavior, not every system directory.
Host load was not controlled; three samples do not establish a performance
distribution. Publication and install exited zero for both variants at the raised
limit; each installed payload produced the expected stdout and on-disk tree.

| Target             | Private registry A/B | No Node A/B | Offline A/B | Quarantine A/B             |
| ------------------ | -------------------- | ----------- | ----------- | -------------------------- |
| Hosted Linux x64   | Unverified           | Unverified  | Unverified  | Third-party EDR unverified |
| Hosted Linux arm64 | Unverified           | Unverified  | Unverified  | Third-party EDR unverified |
| Hosted macOS arm64 | Unverified           | Unverified  | Unverified  | Unverified                 |
| Hosted macOS x64   | Unverified           | Unverified  | Unverified  | Unverified                 |
| Hosted Windows x64 | Unverified           | Unverified  | Unverified  | Unverified                 |

## Platform security collection

Harden Runner v2.22.3 documents **audit only** on hosted macOS/Windows in its
[compatibility matrix](https://github.com/step-security/harden-runner/blob/46b06cea07f9e64621fdf066ba77ac6915163d43/README.md#environment-compatibility-matrix).
Audit mode cannot establish offline success. The collector attempts `sandbox-exec`
network denial on macOS and an outbound firewall rule on disposable Windows runners.
Permission/tool failures and inconclusive connection timeouts become `unverified`
with the exact command output. The Windows rule is removed in `finally`.

For macOS, the collector copies each payload, runs recursive
`xattr -w com.apple.quarantine`, reads the attribute, then records
`spctl --assess --type execute --verbose=4`, `codesign --display --verbose=4`,
`codesign --verify --deep --strict --verbose=4`, and direct CLI execution. For
Windows, it writes and reads `Zone.Identifier` (ZoneId=3), records
`Get-AuthenticodeSignature`, locates `MpCmdRun.exe`, scans the copied payload with
`-Scan -ScanType 3 -File`, then executes it. JSON retains complete commands and
outputs, including nonzero security assessments separately from execution status.

Signing/notarization needs for **both variants remain unverified** until those
outputs exist. Even then, CLI invocation is insufficient evidence for Finder launch,
SmartScreen reputation, organizational allowlisting or third-party EDR. Quarantine
collection uses `measured`, not a synthetic overall security pass. Unavailable
Defender tooling is explicitly unverified, not a passing scan.

## Raw evidence and dispatch handoff

No green dispatch run exists yet. No live result link can honestly be provided.
The local parent's workspace retains the full initial attempts and real command
outputs in `562-initial-sol.log` under the session's supplied log directory. Local
builds and JSON were collected under `/tmp/ai-skills-562-final2/`; earlier
default-registry failure JSON was retained separately. Compiled payloads are removed
after collection. Small raw JSON/log copies are retained under `562-local-evidence/`
and `562-default-registry-limit/` in the task log directory for the parent. These
are local evidence, not portable public links. The final local collection exited
zero and retains archive hashes and source-file fingerprints with the raw commands.

The workflow uploads `spike-evidence-<runner>` containing `build.json` and scenario
JSON; a separate Linux artifact carries empty-allowlist evidence. A green run means
collection succeeded; inspect every scenario's `status`, not just the job badge.
The empty allowlist may also prevent artifact-service egress: preserve the job logs
and namespace evidence if upload fails, then revise the export path without adding
an application egress exception. Runner capabilities and label availability have
not been live-verified by this local session.

GitHub requires a dispatchable workflow to exist on the default branch. Pushing
this new workflow only to the research branch may therefore be insufficient. Safe
parent-owned paths are a reviewed workflow-only bootstrap on the default branch,
followed by dispatch with this research ref, or an isolated public research fork
whose default branch is the exact experiment commit. Record the repository, ref,
head and security environment of the run; fork evidence needs that qualification.
Neither route requires accepting ADR 0008 before measuring. This agent performs
neither route and has not dispatched anything.

After the parent obtains results, the revision must:

1. Link the green collection run and raw artifacts; populate every hosted row and
   footprint metric with exact observations, retaining unsupported cells and errors.
2. Describe actual macOS and Windows assessment output and any demonstrated signing
   or notarization needs, keeping interactive/reputation/third-party EDR unverified.
3. Apply the decision rule below; edit ADR 0008 and its README status together.
4. Amend downstream specifications if the chosen runtime contradicts them, before
   implementing M6/M7. The parent owns issue edits/comments and all remote actions.

## Recommendation and decision rule

**Defer the runtime decision.** The local evidence establishes that both designs
can run without consumer Node/Python tooling and can install offline on this Linux
machine. It does not establish cross-platform equality or superiority. Python's
untrimmed directory costs more bytes/files here; trimming it was not measured.

The issue's two branches overlap when the candidates tie. Apply ADR 0008's explicit
escape hatch first: if B is equally deployable across the measured private-registry,
no-Node and offline restrictions, revise to a single Python engine behind a thin
TypeScript npm launcher. Otherwise accept A only if A is no worse on **every**
restricted criterion, including demonstrated quarantine and footprint limitations.
Missing evidence never satisfies either condition. If neither branch is supported,
retain Proposed and specify the next experiment. Do not invent quantitative
acceptability thresholds or infer notarization approval from an exit-zero CLI.

Read-only inspection of #566, #567, #578 and #386 found no **disproven** downstream
runtime assumption yet. #566 and #578 explicitly assume TypeScript installation;
the Python escape hatch would require their scope/module/fixture expectations to
change. #386 already defers runtime packaging to this decision; its registry limits
and signing work need the eventual evidence. #567's build-plane extraction remains
compatible with either outcome. No issue body was edited. The epic's M6 TypeScript
assumption and #562's demand to change ADR status are provisional against this
evidence gate, not permission to accept a runtime without live measurements.

## Acceptance accounting

| #562 criterion                                     | State in this initial implementation                              |
| -------------------------------------------------- | ----------------------------------------------------------------- |
| Equivalent golden fixture and fail-closed tests    | Implemented locally; workflow runs both suites and parity         |
| Dispatchable multi-OS build/run and JSON uploads   | Implemented; live run/link outstanding                            |
| Private registry, ignore-scripts, no postinstall   | Default upload failure and raised-limit success measured locally  |
| No-Node/offline per OS and variant                 | Local Linux measured; every hosted cell outstanding               |
| Exact quarantine commands/output and signing needs | Collector implemented; macOS/Windows evidence outstanding         |
| Comparison and recommendation                      | Local comparison; defer final runtime selection                   |
| ADR status change and matching index               | Intentionally outstanding under owner evidence requirement        |
| Spike isolated from npm publication                | Research directory outside the package's positive files allowlist |
| No authored JavaScript in prototypes               | TypeScript/Python/shell only; fixture tar contains Markdown data  |

Local verification: `uv run pytest` passed all 684 tests (85% aggregate coverage;
12 spike tests). `bash scripts/validate.sh` passed. The spike's `bun test --coverage`
passed eight tests (86.62% lines, 100% functions), and `bunx tsc --noEmit` passed.
`bun pm pack --dry-run` in the existing gateway listed 29 files, none from research.
