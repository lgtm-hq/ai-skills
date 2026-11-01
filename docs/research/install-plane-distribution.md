# Install-plane distribution experiment (#562)

Date: 2026-11-01. **ADR 0008 remains Proposed.** Registry and no-Node collection
covers both variants on all five targets at the retained R6 head. Independent
restricted direct-runtime measurements are still needed for a runtime decision
under the resolved owner policy below. This throwaway spike is outside the
published npm `files` allowlist and contains no authored JavaScript.

## Current owner policy and recommendation

The binding [security policy][owner-security] and [offline policy][owner-offline]
resolve the earlier questions. **The standalone compiled binary is primary offline
transport, with no install step; npm-only local-file wrapper installation is the
documented fallback.** B's self-contained Python directory is compared by the same
direct-run criterion. Both direct execution and npm fallback decide offline per
OS/variant. Bun local-file failures remain visible evidence, **not a gate**;
[oven-sh/bun#47640][bun-upstream] already tracks the offline reproduction. Bun
remains required alongside npm for registry/private-registry installations.

For #562, record unsigned quarantine/`spctl`/codesign, MotW, SmartScreen and
Defender observations, plus what signing/notarization needs. A signed Mac run is
not required. Developer ID/notarization is the human-secret gate in
[#619](https://github.com/lgtm-hq/ai-skills/issues/619); Authenticode is cost-gated
in [#618](https://github.com/lgtm-hq/ai-skills/issues/618). No paid or third-party EDR
check is required. Free checksums, GitHub artifact/npm attestations, SLSA provenance
and Sigstore/cosign keyless signing remain distribution obligations. Where paid
signing is absent, deliver unsigned but attested; this research does not claim a
production attestation pipeline or fleet security approval.

**Recommendation: retain Proposed until direct-offline measurements are inspected.**
R6 has no independent original-payload direct run under restriction. R8 adds it,
without an install step or package-manager dependency for execution, and judges
its result plus npm local-file installation/execution; Bun results are retained.
Registry's dual-client rule is unchanged. Windows per-program denial remains
unverified without matched same-program controls; Harden Runner's missing same-host
baseline and transferred-payload provenance also remain explicit limits. These
are measured-evidence gaps, not unresolved owner policy. Apply the existing
Python-first tie rule once comparable evidence supports the required criteria;
footprint alone supplies no new acceptance threshold.

All R3–R6 tables below retain **historical raw outcomes under the superseded
both-clients-offline policy**. In particular, POSIX offline `fail` reflects Bun
selection failure under that old rule. It is not a current-policy gate failure,
and cannot be retroactively turned into a direct-runtime pass. No raw JSON is
modified or relabeled, and no earlier run certifies R8.

## Method and evidence identity

[Sources and reproduction](../../research/install-plane-spike/README.md) build:

- **A / ts:** strict TypeScript compiled with `bun build --compile`, natively on
  each supported runner.
- **B / py:** the entire uv-managed python-build-standalone directory, invoked
  with `-I -B`. This conservative untrimmed baseline needs no consumer Python,
  uv, pip, self-extractor or runtime fetch. Symlinks are dereferenced for npm
  transport. Licenses remain in the tree; redistribution needs a separate audit.

Both verify one shared data-only USTAR artifact and SHA-256 inventory, subtract
one capability by set membership, enforce embedded closure and write the same
BOM-preserving golden output. Source parity tests and actual bundled execution
check stdout **and installed bytes**. Portable paths, excluded inventory, closure,
BOM rejection on the index and malformed archives fail before destination writes.
The co-located index is not authenticated; production contracts remain M6/M7 work.

The inspected R3 [PR run 41292001121][pr] and genuine
[workflow_dispatch run 41292078852][dispatch] both completed **successfully** at
`ca2db52669b8611a7d9cd24733c80572516ff94a`. Each contains **12 unique result
JSONs**: ten native (five targets × two variants) plus two dedicated Linux offline
observations. All 24 record that exact source/expected head, empty source status,
and the corresponding event/run identity. Collection success is not scenario
acceptance. Both [PR artifacts][pr-artifacts] and [dispatch artifacts][artifacts]
contain these six evidence artifacts:

| Runner           | Artifact                               | Result JSON names                |
| ---------------- | -------------------------------------- | -------------------------------- |
| ubuntu-24.04     | `spike-evidence-ubuntu-24.04`          | `linux-x64-{ts,py}.json`         |
| ubuntu-24.04-arm | `spike-evidence-ubuntu-24.04-arm`      | `linux-arm64-{ts,py}.json`       |
| macos-15         | `spike-evidence-macos-15`              | `darwin-arm64-{ts,py}.json`      |
| macos-15-intel   | `spike-evidence-macos-15-intel`        | `darwin-x64-{ts,py}.json`        |
| windows-2025     | `spike-evidence-windows-2025`          | `windows-x64-{ts,py}.json`       |
| Dedicated Linux  | `spike-evidence-linux-empty-allowlist` | `linux-x64-{ts,py}-offline.json` |

The additional `spike-linux-payloads` artifact transfers payloads/tooling to the
dedicated job. Raw JSON retains argv, stdout/stderr, exits, timings and source
fingerprints. Pins are Bun **1.4.0**, uv **0.11.26**, CPython **3.14.6** and
Verdaccio **6.2.0**. Verdaccio's transitive setup tree is not locked; launcher
`--bun` flags or Node-style warnings do not certify its entire runtime tree.

## Historical R4 evidence

The R4 [PR run 41295866082][r4-pr] and genuine
[workflow_dispatch run 41295968562][r4-dispatch] both completed **successfully**
at exact clean head `d77da0126b9956bc1b4205416345d16c5a344228`.
Each [PR artifact list][r4-pr-artifacts] / [dispatch artifact list][r4-artifacts]
contains twelve unique schema-3 result JSONs: ten native (five targets × two
variants) and two dedicated offline observations. All 24 have matching
source/expected heads, empty source status, exact event/run identity and run
attempt **1**. The five `build.json` files per run are setup logs, not additional
result cells. Artifact names follow the runner table above.

Both runs agree on these outcomes for **both variants**. Client pairs below are
**Bun / npm**; U means unverified. Client installation success and registry server
cleanup are separate observations.

| Target       | Registry clients | Registry overall | No Node | Local-file control / restricted clients | Offline overall |
| ------------ | ---------------- | ---------------- | ------- | --------------------------------------- | --------------- |
| linux-x64    | Pass / pass      | Pass             | Pass    | Fail / pass in both                     | Fail            |
| linux-arm64  | Pass / pass      | Pass             | Pass    | Fail / pass in both                     | Fail            |
| darwin-arm64 | Pass / pass      | Pass             | Pass    | Fail / pass in both                     | Fail            |
| darwin-x64   | Pass / pass      | Pass             | Pass    | Fail / pass in both                     | Fail            |
| windows-x64  | Pass / pass      | U (cleanup)      | Pass    | Fail / pass in both                     | U (probe only)  |

Every Bun local-file wrapper install still selects all five platform packages;
npm selects the target. The same tarballs and `--offline --ignore-scripts` flags
are used before/during restriction. Linux/macOS record both
`probe_denial_proven=true` and `installer_denial_proven=true` under shared
namespace/sandbox restrictions; Bun's transport failure keeps overall offline
status fail. Windows records probe true but installer false: its bundled Python
IPv4 baseline connects and its restricted probe gets WinError 10013. Exact scoped
firewall cleanup records `verified removed`, exit 0 and `rules absent`.
There are still no same-program positive/restricted controls for Bun, Node or
installed runtimes. Passing npm observations do not establish offline acceptance.

Windows registry termination records `taskkill /PID <owned-root> /T` exit 255,
forced `/T /F` exit 0 and parent reap, with descendant absence explicitly
unverified. Thus its **client installations pass but registry overall is U**.
POSIX registry owned-group absence is verified. The R5 source replaces Windows
PID-tree cleanup with suspended launch into a non-breakaway Job Object, shared
by commands and registry startup. Its failure/success lifecycle tests and
parent-exits/child-keeps-pipes smoke are wired into the native CI test step;
R4 artifacts do not validate that replacement. R5 is separately inspected below.

Both dedicated R4 observations per run remain U: Harden Runner alone has no
same-host unrestricted baseline, and probe/installer denial are false. Their
installer observations remain Bun fail / npm pass. Downloaded payload hashes
still do not bind them to expected source/build metadata. Green dispatch meets
the collection/link criterion at **d77da01 only**; final acceptance needs evidence
for the reviewed head plus disposition of every required failure/unknown.

The footprint timings and detailed quarantine command/output tables below remain
**R3-only historical measurements** at ca2db52. They are not R4 or R5 timings.
Neither earlier artifact set has been modified or relabeled.

## Historical inspected R5 evidence

The R5 [PR run 41299584188][r5-pr] and genuine
[workflow_dispatch run 41299627797][r5-dispatch] completed **successfully** at
exact clean `6d2d86bdfd9a68d6dd9f36ca3fd16619b53c1069`.
Each [PR artifact list][r5-pr-artifacts] / [dispatch artifact list][r5-artifacts]
contains **12 unique schema-3 result JSONs**: ten native plus two dedicated Linux
offline observations. All 24 raw documents were inspected for exact matching
source/expected heads, empty source status, event/run identity and attempt **1**.
The five `build.json` files per run remain setup logs, not scenario cells.

Both runs agree for **both variants**. Client pairs are **Bun / npm**; U means
unverified. These are R5 observations, separate from the historical R3 tables.

| Target       | Registry clients | Registry overall | No Node | Local-file control / restricted clients | Offline overall |
| ------------ | ---------------- | ---------------- | ------- | --------------------------------------- | --------------- |
| linux-x64    | Pass / pass      | Pass             | Pass    | Fail / pass in both                     | Fail            |
| linux-arm64  | Pass / pass      | Pass             | Pass    | Fail / pass in both                     | Fail            |
| darwin-arm64 | Pass / pass      | Pass             | Pass    | Fail / pass in both                     | Fail            |
| darwin-x64   | Pass / pass      | Pass             | Pass    | Fail / pass in both                     | Fail            |
| windows-x64  | Pass / pass      | Pass             | Pass    | Fail / pass in both                     | U (probe only)  |

Windows registry cleanup now records an **owned non-breakaway Windows Job
Object**, successful termination, `active_processes=0`, `parent_reaped=true` and
`job_handle_closed=true`. This establishes the observed R5 registry cleanup
result, replacing R4's unverified descendant absence. It does not prove Windows
installer egress denial: offline remains U with probe true, installer false and
verified exact firewall rule removal. POSIX offline remains fail because Bun
selects all five local-file platform packages; npm selects its target. Both
dedicated observations remain U without a same-host unrestricted Harden Runner
baseline. Payload-source binding remains explicitly unverified in every cell.

The separate [Python-only CI run 41299584834][r5-python] failed five adversarial
TypeScript cases because Bun was absent (821 passed, 16 skipped, 5 failed).
R6 restores the optional-Bun test contract while keeping dedicated parity required,
rejects raw empty extension headers before Python tarfile interpretation, checks
exact nonsymlink output trees, and preserves completed registry evidence on close
failure. These source corrections have local regressions; **R5 artifacts do not
validate R6**. R6 is inspected separately below; existing raw evidence is unchanged.
Green R5 spike collection supplies the dispatch/link evidence at **6d2d86b only**;
it does not establish scenario acceptance, owner approval or ADR acceptance.

## Inspected historical R6 evidence (10205e3 only)

The retained [PR run 41303888697][r6-pr] and green
[workflow_dispatch run 41304035426][r6-dispatch] both completed successfully at
`10205e3519ab610c97fd2a846bfc54e9ecbe3048`. Each contains twelve unique schema-3
result JSONs (ten native plus two dedicated offline), with exact matching
source/expected head, empty source status, event/run identity and attempt 1.
The five build JSONs per run are setup evidence, not scenario cells. The retained
`562-r6-hosted-summary.json` agrees with the inspected 24 raw result documents.

Both runs show, for both variants:

| Targets                          | Registry Bun / npm and overall | No Node | Local-file Bun / npm (control and restricted)    | Historical offline overall  | Independent direct offline |
| -------------------------------- | ------------------------------ | ------- | ------------------------------------------------ | --------------------------- | -------------------------- |
| Linux x64/arm64, macOS x64/arm64 | Pass / pass, pass              | Pass    | Fail / pass                                      | Fail (old dual-client rule) | Not collected              |
| Windows x64                      | Pass / pass, pass              | Pass    | Fail / pass                                      | Unverified (probe only)     | Not collected              |
| Dedicated Linux                  | Not run                        | Not run | Fail / pass restricted; no unrestricted interval | Unverified                  | Not collected              |

Native Linux/macOS prove shared probe/installer denial. Windows has probe denial
true, installer denial false and verified rule removal. Both dedicated cells lack
a same-host unrestricted Harden Runner control; payload-source identity remains
unverified everywhere. Native macOS/Windows security is measured; Linux has no
native quarantine control. The exact R3 numeric/security tables below remain R3
observations, not R6 measurements. R6 supplies historical dispatch/link evidence
only, and cannot certify subsequent source corrections or the new direct cell.

## R7 source corrections (local verification only)

Fresh review findings exposed four reachable failures after R6: missing evidence
when empty-allowlist checkout fails, silently discarded duplicate index keys,
a payload-mutable golden oracle, and partial output that prevents installation
retry. R7 records acquisition step outcomes without checkout, exports them to the
runner log/summary before best-effort artifact upload, rejects decoded duplicate
keys in both runtimes, snapshots the collector's trusted golden before execution,
and stages writes with cleanup before publishing into a fresh reserved target.
Acquisition-only evidence stays **unverified**, with no source-head or denial
claim; unavailable artifacts never count as passing scenario evidence.

Offline regressions cover blocked checkout/upload, literal and escaped-equivalent
duplicate keys, a real subprocess rewriting its fixture and printing `{}` with an
empty target, and injected mkdir/write failures followed by successful retries.
Existing targets are preserved. The touched tree verifier also rejects Windows
reparse metadata, and malformed-input Python tests run without Bun. Four fixture
token literals that triggered B105 in quality run 41303889058 (job 124840243729)
are replaced with generated disposable values while retaining redaction checks.
Parent verification logs were moved outside the worktree to the coder profile
logs under `logs/tick-1229/`; `.lintro/562-r7-*.log` is not a committed artifact.

The actual [R7 PR run 41307370871][r7-pr] at
`774ba560bcb0fdffa21b41c6e9127a11d26a02eb`
failed all five native test steps with `ModuleNotFoundError: yaml`, before payload
build/measurement. Those failed jobs provide **no native scenario evidence**.
Missing payload acquisition in the dependent offline job is not a scenario pass.
R6 evidence above applies only to 10205e3. Historical R3/R4/R5/R6 raw JSON is unchanged.

## R8 source corrections (local verification only)

The actual isolated test command now reads exact pytest/assertpy/PyYAML versions
from `uv.lock` and uses `--no-project --isolated`, preventing a local project
`.venv` from masking omitted test dependencies. The checkout-failure regression
executes the real Ubuntu fallback on Linux only, avoiding Windows Store Python or
WSL aliases. `pins.sh` already uses the runner's `pythonLocation` interpreter
rather than `python3`; that pins step succeeded on all five R7 runners. No Windows
execution proof is inferred from Linux tests.

Each POSIX shutdown phase now shares one monotonic deadline across signal, parent
wait and group polling. Deterministic modeled-time regressions reproduce ignored
SIGTERM and early parent exit, including signal overhead. Windows owned-job
semantics are preserved. A confirmed Defender threat now remains `fail` when an
independent MotW write/read fails; command-combination regressions use mocked
boundaries, not native security evidence.

Each offline worker now executes each original standalone A/B payload in a fresh
HOME **before packing or installing its wrapper**, under the selected restriction.
It records `direct_execution` and exact commands independently. An unavailable
packer cannot erase that direct observation. The top-level restricted direct
cell retains the execution observation and qualifies denial separately. Offline
rollup uses direct plus npm only; Bun's per-client failure remains visible.
Windows rules include the direct entry paths, but no same-program controls have
been fabricated: direct and overall remain unverified there. The dedicated
Harden Runner job remains unverified without its positive baseline. Registry
still requires both clients. Local regressions are collector-contract tests, not
new hosted measurements.

Local logs are outside the worktree at the coder profile's
`logs/562-r8-*.log`. The exact CI Python pin, **3.14.6**, is absent locally; its
actual `test-ci.sh` invocation fails interpreter discovery with downloads disabled.
The installed **3.14.7** interpreter is used for the isolated local smoke and is
not interchangeable with pinned hosted evidence. Only the small locked test
dependencies may be fetched; no runtime/toolchain bundle is installed. No R8
hosted validation or ADR acceptance is claimed.

## R3 restricted-scenario comparison

Each client gets fresh HOME, temp, config and caches. The private registry has no
uplinks; both clients install the wrapper and optional os/cpu package with
`--ignore-scripts`, then check platform selection, payload hashes/modes and golden
execution. Registry-only configuration is not an OS firewall around clients.

Offline uses actual local-file wrapper/platform tarball installation with fresh
caches, `--offline --ignore-scripts` and verified installed bytes. The
**network-unrestricted control retains these same offline flags** and tarballs.
In this table, pairs are **Bun / npm**, and `U` means **unverified**. The installer
observations stay separate from proof that their executables cannot use egress.

| Target       | Variant | Registry clients | No Node | Same-input control clients | Restricted install observations | Verified offline |
| ------------ | ------- | ---------------- | ------- | -------------------------- | ------------------------------- | ---------------- |
| linux-x64    | A       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                     | Fail             |
| linux-x64    | B       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                     | Fail             |
| linux-arm64  | A       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                     | Fail             |
| linux-arm64  | B       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                     | Fail             |
| darwin-arm64 | A       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                     | Fail             |
| darwin-arm64 | B       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                     | Fail             |
| darwin-x64   | A       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                     | Fail             |
| darwin-x64   | B       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                     | Fail             |
| windows-x64  | A       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                     | U (probe only)   |
| windows-x64  | B       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                     | U (probe only)   |

These outcomes reproduce across **both R3 runs**. All registry installs select only
their target, execute and match build bytes. Every local-file Bun install selects
**all five** platform packages rather than its target; npm selects its target.
The payload itself executes and matches in both clients. Bun's incompatible
platform assertion correctly fails before and during restriction on all five
targets for both variants. Equal failure does not prove equal deployability.
Neither client nor the failing assertion has been removed.

Linux's shared network namespace has a connected IPv4 baseline followed by errno
101 `Network is unreachable`; macOS's shared sandbox gives errno 1
`Operation not permitted`. These restrictions cover probe and installers together.
The Linux sudo/setpriv fallback runs installers as UID/GID 1001 with no
supplementary groups. These observations are not Harden Runner-only proof.

**Windows R3 repaired rule creation, but proves only Python probe denial.** All
scoped `New-NetFirewallRule` commands exit **0** with full executable identities;
future paths expand the existing `RUNNER~1` ancestor to `runneradmin`. Bundled
Python's IPv4 baseline connects; its restricted probe gets WinError **10013** /
errno **13**, explicit access denial. Both clients actually install under the
rules. Finally, exact per-run rules are absent and cleanup exits **0**.

Rules for `bun.exe`, `node.exe` and future installed runtimes have **no matched
same-program positive/restricted control**. Python denial cannot certify them.
The unchanged schema-2 R3 JSON says `denial_proven=true` and top-level `fail`;
those fields overstate installation-level denial. The table interprets Windows
offline as **U**, retaining Bun fail / npm pass as installation observations.
Even a passing npm observation is not a verified offline pass. R4 separates
`probe_denial_proven` from `installer_denial_proven`; Windows keeps the latter
false and the restricted cell unverified. Rule setup/cleanup failures also remain
unverified. No host/control-plane firewall expansion or invented runtime probe is
used.

The dedicated first-step Harden Runner empty-allowlist job remains **U for both
variants in both runs**. There is no same-host unrestricted baseline; IPv4 gives
errno 111 `Connection refused` / `inconclusive`. Informational IPv6 errno 101
does not prove denial. Its installer observations are again Bun fail / npm pass.

R3 registry process-tree records show POSIX owned groups absent. Windows records
graceful `taskkill /T` exit **255**, forced `/T /F` exit **0**, then parent reap.
Its schema-2 `pass` is command evidence, not descendant enumeration. R4 retains
those actions and reports Windows descendant absence **unverified**, including
when graceful taskkill succeeds. Registry summaries are downgraded accordingly;
the R3 registry client installation passes remain historical observations.

## R3 footprint

The following values come only from **dispatch 41292078852** native JSONs.
Archive bytes and timing vary across runs; no R2 measurements are relabeled.
Times are three fresh processes in milliseconds, rounded to three decimals.
Page caches were not flushed, so these are not disk-cold benchmarks.

| Target       | Variant | Payload bytes | Files | Archive bytes | Three process times (ms) |
| ------------ | ------- | ------------- | ----- | ------------- | ------------------------ |
| linux-x64    | A       | 82,550,499    | 4     | 36,592,297    | 24.506, 21.314, 21.578   |
| linux-x64    | B       | 205,508,411   | 4,761 | 73,244,380    | 33.030, 32.308, 32.207   |
| linux-arm64  | A       | 82,506,259    | 4     | 36,587,067    | 18.191, 17.998, 16.289   |
| linux-arm64  | B       | 157,311,092   | 4,761 | 58,582,754    | 32.343, 31.133, 30.872   |
| darwin-arm64 | A       | 63,921,293    | 4     | 25,896,207    | 29.357, 17.530, 16.994   |
| darwin-arm64 | B       | 107,714,795   | 1,894 | 43,333,654    | 33.487, 33.712, 34.410   |
| darwin-x64   | A       | 70,715,323    | 4     | 28,464,914    | 95.117, 50.957, 51.757   |
| darwin-x64   | B       | 110,081,287   | 1,894 | 43,377,518    | 54.670, 56.362, 54.848   |
| windows-x64  | A       | 88,833,563    | 4     | 39,805,349    | 54.118, 37.652, 38.198   |
| windows-x64  | B       | 65,659,506    | 3,163 | 22,731,708    | 65.292, 59.907, 59.377   |

All **60** no-Node processes across the two runs pass with the cache directory
blocked and no other HOME files observed. Tool directories are filtered from
PATH and Node/Bun resolution checked; tools are not physically uninstalled.
R4 also checks `nodejs`/`bunx` aliases and makes observed extra HOME files fail.
Writes outside HOME and read-only payload operation remain unverified.
Windows `LongPathsEnabled=1`; observed quarantine-tree maxima are A **103** and
B **180** characters, not deliberate MAX_PATH tests. No size/timing budget was
specified by #562.

## R3 quarantine and signatures

The inspected R3 security outcomes agree across PR and dispatch. Exact absolute
argv and complete outputs are in each native JSON's `quarantine.commands`.
In the commands below, `ENTRY` denotes A's `spike`
(`spike.exe` on Windows) or B's `runtime/bin/python3` (`runtime/python.exe` on
Windows), inside the disposable quarantine tree; `TREE` denotes that tree.
Quoted output excerpts are verbatim, with path prefixes omitted where stated.

On both macOS targets and variants:

```text
spctl --status                                     exit 0: assessments enabled
xattr -r -w com.apple.quarantine '0083;67240000;InstallPlaneSpike;' TREE
                                                    exit 0, no output
xattr -p com.apple.quarantine ENTRY                 exit 0: 0083;67240000;InstallPlaneSpike;
spctl --assess --type execute --verbose=4 ENTRY
codesign --display --verbose=4 ENTRY
codesign --verify --deep --strict --verbose=4 ENTRY
```

| Target / variant | `spctl --assess` exit and stderr excerpt (after path)         | `codesign --display` excerpt                                        | `codesign --verify` exit and excerpt                          |
| ---------------- | ------------------------------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------- |
| darwin-arm64 A   | 1: `invalid signature (code or signature have been modified)` | 0: `Signature=adhoc`, `TeamIdentifier=not set`                      | 1: `invalid signature (code or signature have been modified)` |
| darwin-arm64 B   | 3: `rejected`                                                 | 0: `Signature=adhoc`, `TeamIdentifier=not set`                      | 0: `valid on disk`, `satisfies its Designated Requirement`    |
| darwin-x64 A     | 1: `invalid signature (code or signature have been modified)` | 0: `Authority=Developer ID Application: Jarred Sumner (7FRXF46ZSN)` | 1: `invalid signature (code or signature have been modified)` |
| darwin-x64 B     | 3: `rejected`, `source=no usable signature`                   | 1: `code object is not signed at all`                               | 1: `code object is not signed at all`                         |

All four quarantined direct CLI executions exited **0**, matched golden stdout
and wrote verified bytes. A's embedded signature metadata does not constitute a
valid signature for the compiled output. B's arm64 ad-hoc signature verifies on
disk but is rejected by assessment; B x64 is unsigned. These artifacts do not
demonstrate acceptable assessed distribution for either variant. Producing and
assessing appropriately signed artifacts, and testing notarization/Finder launch,
remain necessary before claiming that delivery route. Required organizational
signing/notarization policy is now resolved above; these historical measurements
do not establish fleet approval. Signed delivery verification belongs to #619.

Windows A and B both record these actual observations:

```text
Get-MpComputerStatus | ConvertTo-Json -Depth 4       exit 0
  "AMServiceEnabled": true, "AntivirusEnabled": true
  "RealTimeProtectionEnabled": false, "IoavProtectionEnabled": false
  "BehaviorMonitorEnabled": false
Set-Content -LiteralPath ENTRY -Stream Zone.Identifier -Value "[ZoneTransfer]`nZoneId=3"
Get-Content -LiteralPath ENTRY -Stream Zone.Identifier
                                                    exit 0:
[ZoneTransfer]
ZoneId=3
Get-AuthenticodeSignature -LiteralPath ENTRY | Format-List *
                                                    exit 0, excerpt:
Status                 : NotSigned
SignatureType          : None
MpCmdRun.exe -Scan -ScanType 3 -File TREE            exit 0:
Scan starting...
Scan finished.
```

The dispatch's final scanner line for A is:

```text
Scanning C:\Users\RUNNER~1\AppData\Local\Temp\spike-measure-8oeqvin0\quarantine-ts found no threats.
```

B has the identical line ending in `quarantine-py found no threats.`
Both scans have empty stderr. Both direct CreateProcess launches exit **0** and
pass the golden/tree checks. This is a clean **custom scan**, with the engine
service enabled, not real-time endpoint protection approval. MotW was set/read on
the entry executable only. Shell/SmartScreen reputation enforcement, organizational
signing enforcement and third-party EDR remain unverified for both variants;
the resolved policy requires neither paid signing nor third-party EDR for #562.
Linux has no macOS/Windows security observation; third-party EDR is unverified too.

## Revision boundary and remaining work

The R2 runs [41288233178][r2] and [41290059704][r2-dispatch] predate these R3
observations; R2 Windows stopped at firewall Error 87 without restricted installs.
The R3 green dispatch now satisfies the dispatch collection/link criterion at
`ca2db52`. R4, R5 and R6 collection are separately inspected above; none validates R8.

R4's schema **3** enforces a clean checkout and required matching expected head in
hosted mode, records `GITHUB_RUN_ATTEMPT`, and labels local runs as local
observations. The R3 clean status was inspected, rather than enforced. Downloaded
offline payloads are hashed, but are **not bound to the expected source head or
build metadata**; R4 explicitly records that source identity as unverified.
This is not end-to-end fail-closed payload provenance. Shared malformed USTAR
mutations now cover archive length, hidden NUL suffixes/prefix bytes and invalid
octal metadata; empty size is rejected in both runtimes. Golden/BOM parity and
bounded reads remain required.

**Retain Proposed (Part of #562) for the missing direct-offline experiment.**
The owner has disposed of the policy questions. Bun local-file failure is evidence
only; unsigned assessment results and documented signing requirements satisfy the
security-policy scope without a signed run. Missing direct execution evidence
cannot establish either equality or superiority under the Python-first rule.

The remaining evidence work on **#562** is concrete:

1. Inspect current reviewed-head hosted JSON for both original standalone variants
   running under restriction on all five targets, plus npm local-file fallback.
   R6 lacks the direct cell and R7 never reached native measurement. Link a genuine
   green dispatch for the corrected collector; local regressions cannot certify it.
2. Keep Windows installer/direct-runtime denial unverified until matched
   same-program controls exist. Python probe denial alone is insufficient.
3. Preserve the empty-allowlist Harden Runner experiment's missing same-host
   unrestricted baseline; namespace/sandbox proof does not repair it.
4. Bind transferred payload hashes and build metadata to expected source before
   claiming verified provenance; current evidence explicitly cannot do so.
5. Apply the issue's decision rule after inspecting comparable evidence: revise to
   Python behind a thin TypeScript npm launcher if B is equally deployable; accept
   A only if it is no worse on every required restricted criterion. Footprint has
   no specified budget. Update ADR/index/README together and reconcile
   #566/#567/#578/#386 when justified. No new owner answer is needed.

For a future signed Mac delivery route, A's final compiled Mach-O needs a valid
Developer ID Application signature with hardened runtime and reviewed Bun/JIT
entitlements; its inherited/ad-hoc signature is insufficient. B needs nested
Mach-O dylibs/extensions and the interpreter signed inside-out, with reviewed
interpreter/extension entitlements. Notarize the final archive/container with
`notarytool` and assess the distributed output with `spctl`. A bare executable or
directory/zip cannot receive a stapled ticket; a supported signed pkg/app/dmg can.
Exact entitlements and signed/notarized/Finder verification remain the #619
human-secret-gated work, not invented #562 evidence. Windows Authenticode remains
in #618; MotW direct CreateProcess does not test shell/SmartScreen reputation. No
paid EDR or scanner is required.

Only optional M5 NITs belong in **#614**: locking Verdaccio's transitive setup
runtime tree and attributing that tree, broader cache/read-only-runtime and CPU/OS
compatibility coverage, and support for legitimate tilde paths currently rejected
conservatively. These do not replace #562 acceptance. Required process ownership,
security, controls, provenance and ADR finalization are not deferred to #614.

[owner-security]: https://github.com/lgtm-hq/ai-skills/issues/562#issuecomment-6557818942
[owner-offline]: https://github.com/lgtm-hq/ai-skills/issues/562#issuecomment-6557886641
[bun-upstream]: https://github.com/oven-sh/bun/issues/47640
[r6-pr]: https://github.com/lgtm-hq/ai-skills/actions/runs/41303888697
[r6-dispatch]: https://github.com/lgtm-hq/ai-skills/actions/runs/41304035426
[r7-pr]: https://github.com/lgtm-hq/ai-skills/actions/runs/41307370871
[r5-pr]: https://github.com/lgtm-hq/ai-skills/actions/runs/41299584188
[r5-dispatch]: https://github.com/lgtm-hq/ai-skills/actions/runs/41299627797
[r5-pr-artifacts]: https://github.com/lgtm-hq/ai-skills/actions/runs/41299584188#artifacts
[r5-artifacts]: https://github.com/lgtm-hq/ai-skills/actions/runs/41299627797#artifacts
[r5-python]: https://github.com/lgtm-hq/ai-skills/actions/runs/41299584834/job/124828308430
[r4-pr]: https://github.com/lgtm-hq/ai-skills/actions/runs/41295866082
[r4-dispatch]: https://github.com/lgtm-hq/ai-skills/actions/runs/41295968562
[r4-pr-artifacts]: https://github.com/lgtm-hq/ai-skills/actions/runs/41295866082#artifacts
[r4-artifacts]: https://github.com/lgtm-hq/ai-skills/actions/runs/41295968562#artifacts
[pr]: https://github.com/lgtm-hq/ai-skills/actions/runs/41292001121
[dispatch]: https://github.com/lgtm-hq/ai-skills/actions/runs/41292078852
[pr-artifacts]: https://github.com/lgtm-hq/ai-skills/actions/runs/41292001121#artifacts
[artifacts]: https://github.com/lgtm-hq/ai-skills/actions/runs/41292078852#artifacts
[r2]: https://github.com/lgtm-hq/ai-skills/actions/runs/41288233178
[r2-dispatch]: https://github.com/lgtm-hq/ai-skills/actions/runs/41290059704
