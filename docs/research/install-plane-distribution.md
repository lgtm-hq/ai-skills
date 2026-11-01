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
`ca2db52`. It supplies no hosted evidence for this later R4 code.

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

The parent retains these concrete steps in existing M5 batch **#614**:

1. Review/push R4 and inspect the next existing collection tick's raw JSON. Windows
   installer denial stays unverified until each relevant executable has matched
   same-program controls, or the owner disposes of that unmet criterion.
   Windows process-tree enumeration is deferred: bounded taskkill/reap evidence
   alone cannot establish absence, so R4 makes no such claim.
2. Isolate the Bun local-file wrapper selection failure and obtain an explicit
   disposition against deployment requirements. A direct platform-tarball control
   may diagnose transport, but cannot replace the required wrapper/client cell.
3. Establish a valid same-host empty-allowlist Harden Runner control or obtain
   owner disposition. Keep the first-step restriction and failing observations.
4. Obtain signing/notarization, Finder/SmartScreen and EDR requirements for the
   observed assessment failures/unsigned artifacts. Test appropriately signed
   artifacts and the required security route before accepting that route.
5. Bind transferred payload hashes/build metadata to expected source identity
   before claiming verified provenance. This is explicitly unverified in R4;
   no extra distribution experiment or dependency install is added here.
   Verdaccio transitive locking/runtime-tree attribution and broader cache,
   CPU/OS compatibility tests remain outside this small spike's proof.
   Conservative tilde rejection remains: legitimate tilde paths can produce U,
   but unverified program identities are not broadened.
6. Apply the existing Python-first decision rule only after these failures and
   owner requirements have dispositions. Update ADR/index together and reconcile
   #566/#567/#578/#386 then. ADR acceptance and #562 completion remain open.

[pr]: https://github.com/lgtm-hq/ai-skills/actions/runs/41292001121
[dispatch]: https://github.com/lgtm-hq/ai-skills/actions/runs/41292078852
[pr-artifacts]: https://github.com/lgtm-hq/ai-skills/actions/runs/41292001121#artifacts
[artifacts]: https://github.com/lgtm-hq/ai-skills/actions/runs/41292078852#artifacts
[r2]: https://github.com/lgtm-hq/ai-skills/actions/runs/41288233178
[r2-dispatch]: https://github.com/lgtm-hq/ai-skills/actions/runs/41290059704
