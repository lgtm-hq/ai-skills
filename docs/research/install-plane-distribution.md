# Install-plane distribution experiment (#562)

Date: 2026-11-01. **ADR 0008 remains Proposed.** Registry and no-Node collection
now covers both variants on all five targets. Offline failures and unknowns still
prevent a runtime decision. This throwaway spike is outside the published npm
`files` allowlist and contains no authored JavaScript.

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

## Inspected R5 evidence (not R6 validation)

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
validate R6**, and no R6 hosted proof is claimed. Existing raw evidence is unchanged.
Green R5 spike collection supplies the dispatch/link evidence at **6d2d86b only**;
it does not establish scenario acceptance, owner approval or ADR acceptance.

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
Local command logs are retained under `.lintro/562-r7-*.log`.

No R7 hosted validation is claimed. R6 PR run 41303888697 and dispatch 41304035426
apply only to `10205e3519ab610c97fd2a846bfc54e9ecbe3048`, regardless of their
eventual results. Historical R3/R4/R5 tables and raw JSON remain unchanged.
ADR 0008 stays Proposed; owner security/signing policy, the dual-client offline
disposition, Windows installer denial, the Harden Runner baseline and payload
provenance remain required on #562. Optional NITs remain on #614.

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
signing/notarization policy is unknown; no fleet approval is inferred.

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
signing policy and third-party EDR remain unknown for both variants. Linux has no
macOS/Windows security observation; it remains unverified for third-party EDR too.

## Revision boundary and remaining work

The R2 runs [41288233178][r2] and [41290059704][r2-dispatch] predate these R3
observations; R2 Windows stopped at firewall Error 87 without restricted installs.
The R3 green dispatch now satisfies the dispatch collection/link criterion at
`ca2db52`. R4 and R5 collection are separately inspected above; none validates R6.

R4's schema **3** enforces a clean checkout and required matching expected head in
hosted mode, records `GITHUB_RUN_ATTEMPT`, and labels local runs as local
observations. The R3 clean status was inspected, rather than enforced. Downloaded
offline payloads are hashed, but are **not bound to the expected source head or
build metadata**; R4 explicitly records that source identity as unverified.
This is not end-to-end fail-closed payload provenance. Shared malformed USTAR
mutations now cover archive length, hidden NUL suffixes/prefix bytes and invalid
octal metadata; empty size is rejected in both runtimes. Golden/BOM parity and
bounded reads remain required.

**Defer the runtime decision; retain Proposed (Part of #562).** Compare both
variants on **every** restricted criterion, including observed quarantine,
signature/assessment failures and owner-required security. Passing registry,
no-Node or other core scenarios cannot bypass required security. Unknown
Harden Runner/Windows denial and fleet security scope establish no equality.
Identical Bun failures need owner disposition; footprint without a specified
threshold cannot choose the runtime. No runtime choice or waiver is inferred.

These required acceptance steps remain tracked on **[#562][owner-policy]**.
The [public owner-policy gate][owner-policy] remains unanswered: both clients and
all required signing/security/offline/control criteria remain required, with no
waiver inferred. This work is **Part of #562** and does not close it.

1. Inspect hosted evidence for the final reviewed source; R5's Windows registry
   owned-job cleanup is inspected, while R6 hosted validation remains pending.
   Windows installer denial remains
   unverified until each relevant executable has matched same-program controls,
   or the owner explicitly disposes of the unmet criterion.
2. Isolate the Bun local-file wrapper selection failure and obtain an explicit
   disposition against deployment requirements. A direct platform-tarball control
   may diagnose transport, but cannot replace the required wrapper/client cell.
3. Establish a valid same-host empty-allowlist Harden Runner control or obtain
   owner disposition. Keep the first-step restriction and failing observations.
4. Obtain signing/notarization, Finder/SmartScreen and EDR requirements for the
   observed assessment failures/unsigned artifacts. Test appropriately signed
   artifacts and the required security route before accepting that route.
5. Bind transferred payload hashes/build metadata to expected source identity
   before claiming verified provenance. This remains explicitly unverified in R5.
6. Apply the existing Python-first decision rule only after these failures and
   owner requirements have dispositions. Update ADR/index together and reconcile
   #566/#567/#578/#386 then. ADR acceptance and #562 completion remain open.

Only optional M5 NITs belong in **#614**: locking Verdaccio's transitive setup
runtime tree and attributing that tree, broader cache/read-only-runtime and CPU/OS
compatibility coverage, and support for legitimate tilde paths currently rejected
conservatively. These do not replace #562 acceptance. Required process ownership,
security, controls, provenance and ADR finalization are not deferred to #614.

[owner-policy]: https://github.com/lgtm-hq/ai-skills/issues/562#issuecomment-6556223222
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
