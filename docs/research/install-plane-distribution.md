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

The inspected R2 [PR-trigger run 41288233178][r2] completed **successfully** at
`1e5bdc76acf9e5667c19b2425a0c5c4676b90f11`. Its 12 unique result JSONs comprise
10 native observations (five targets × two variants) and two dedicated Linux
offline observations. Every JSON records matching source/expected heads and a
clean checkout. Artifacts on that run are:

| Runner           | Artifact                               | Result JSON names                |
| ---------------- | -------------------------------------- | -------------------------------- |
| ubuntu-24.04     | `spike-evidence-ubuntu-24.04`          | `linux-x64-{ts,py}.json`         |
| ubuntu-24.04-arm | `spike-evidence-ubuntu-24.04-arm`      | `linux-arm64-{ts,py}.json`       |
| macos-15         | `spike-evidence-macos-15`              | `darwin-arm64-{ts,py}.json`      |
| macos-15-intel   | `spike-evidence-macos-15-intel`        | `darwin-x64-{ts,py}.json`        |
| windows-2025     | `spike-evidence-windows-2025`          | `windows-x64-{ts,py}.json`       |
| Dedicated Linux  | `spike-evidence-linux-empty-allowlist` | `linux-x64-{ts,py}-offline.json` |

Use the [run's artifact list][artifacts] for raw argv, stdout/stderr, exits,
timings, build metadata and source fingerprints. The tool pins are Bun **1.4.0**,
uv **0.11.26**, CPython **3.14.6**, Verdaccio **6.2.0**. The entire Verdaccio
transitive setup tree is not locked. Its `(node:PID)` stderr warnings do not
establish execution under Bun despite the launcher's `--bun` flag.
The separate [CI run 41288233753][ci] succeeded (739 collected, 733 passed,
6 skipped). A green collector or CI badge is not a scenario pass.

## R2 restricted-scenario comparison

Each client gets fresh HOME, temp, config and caches. Registry publication uses
cached `bun x --bun --no-install verdaccio@6.2.0`, no uplinks, a 512 MB request
limit and a disposable account. Both measured clients install exact wrapper and
optional os/cpu packages with `--ignore-scripts`; payload hashes/modes, matching
platform selection and execution must all pass. Other platforms are empty
stand-ins. Registry-only configuration is not an OS firewall around clients.

Offline uses real package-manager installation of local wrapper/platform
tarballs, fresh caches, `--offline --ignore-scripts`, and verified payload bytes.
The **network-unrestricted control retains those same offline flags** and uses
the identical tarballs. It is not a fully unrestricted installer control.

In the table, client pairs are **Bun / npm**. `U` means **unverified**, never pass.
The overall offline result additionally requires proven same-host egress denial.

| Target       | Variant | Registry clients | No Node | Same-input control clients | Restricted offline clients | Overall offline |
| ------------ | ------- | ---------------- | ------- | -------------------------- | -------------------------- | --------------- |
| linux-x64    | A       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                | Fail            |
| linux-x64    | B       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                | Fail            |
| linux-arm64  | A       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                | Fail            |
| linux-arm64  | B       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                | Fail            |
| darwin-arm64 | A       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                | Fail            |
| darwin-arm64 | B       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                | Fail            |
| darwin-x64   | A       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                | Fail            |
| darwin-x64   | B       | Pass / pass      | Pass    | Fail / pass                | Fail / pass                | Fail            |
| windows-x64  | A       | Pass / pass      | Pass    | Fail / pass                | U / U (not run)            | U               |
| windows-x64  | B       | Pass / pass      | Pass    | Fail / pass                | U / U (not run)            | U               |

Registry readiness reached HTTP 200 and account creation HTTP 201 everywhere.
Every registry client selected only its target and executed verified payloads.
For all ten network-unrestricted local-file controls, Bun installed **all five**
platform packages; npm installed only its target. Both matching payloads executed,
but Bun correctly failed the incompatible-platform assertion. Linux/macOS
restricted installations reproduced this exact selection failure. Identical
failures implicate this transport/client combination, not either runtime, and do
not prove deployability. No failing client or assertion has been removed.

Linux namespace probes show IPv4 connected before isolation, then errno 101
`Network is unreachable`; macOS `sandbox-exec` gives errno 1
`Operation not permitted` after a connected baseline. Linux's sudo/setpriv fallback
runs installers at UID/GID 1001 with supplementary groups empty. Neither mechanism
is credited to Harden Runner. Timeout/DROP and missing baselines are inconclusive.

Windows' IPv4 baseline connected, but `New-NetFirewallRule` exited **1** after
creating the first rule. The ordered argv first names Node, then a **future**
Python payload under `C:\Users\RUNNER~1\...\client-py-bun\...\python.exe`.
Its stderr excerpt is:

```text
New-NetFirewallRule : The parameter is incorrect.
FullyQualifiedErrorId : Windows System Error 87,New-NetFirewallRule
```

No restricted Windows probe or install happened. Cleanup exited **0** with
`rules absent`. R3 resolves the existing ancestor to its full local path before
appending future destination components, rejects unresolved short/UNC/device
identities, and records each exact scoped program before rule creation. It retains
per-run rule ownership, profiles, setup diagnostics and verified cleanup. This
repairs the observed parameter boundary; it is **not yet hosted Windows proof**.
The runner agent/control plane and host-wide firewall policy remain outside scope.

The dedicated first-step empty-allowlist Linux job remains **U for A and B**:
there is no same-host unrestricted baseline, and IPv4 gave errno 111
`Connection refused` / `inconclusive`. Informational IPv6 errno 101 is not proof.
Its installer observations again show Bun fail / npm pass. Collection success
establishes neither Harden Runner denial nor offline acceptance.

## R2 footprint

Exact bytes and file counts below are measured payloads/archives. Three times are
fresh processes in milliseconds, rounded to three decimals. Page caches were not
flushed, so these are not disk-cold benchmarks.

| Target       | Variant | Payload bytes | Files | Archive bytes | Three process times (ms) |
| ------------ | ------- | ------------- | ----- | ------------- | ------------------------ |
| linux-x64    | A       | 82,550,499    | 4     | 36,592,085    | 19.622, 19.812, 21.793   |
| linux-x64    | B       | 205,507,858   | 4,761 | 73,244,695    | 32.848, 32.938, 32.330   |
| linux-arm64  | A       | 82,506,259    | 4     | 36,586,873    | 19.695, 17.220, 17.309   |
| linux-arm64  | B       | 157,310,539   | 4,761 | 58,581,108    | 32.658, 32.163, 32.385   |
| darwin-arm64 | A       | 63,921,293    | 4     | 25,896,076    | 67.056, 30.247, 80.559   |
| darwin-arm64 | B       | 107,714,242   | 1,894 | 43,333,867    | 45.462, 37.879, 39.691   |
| darwin-x64   | A       | 70,715,323    | 4     | 28,464,795    | 89.216, 48.316, 48.614   |
| darwin-x64   | B       | 110,080,734   | 1,894 | 43,377,973    | 63.923, 73.634, 77.606   |
| windows-x64  | A       | 88,833,051    | 4     | 39,805,142    | 45.529, 33.998, 33.246   |
| windows-x64  | B       | 65,658,953    | 3,163 | 22,730,605    | 87.812, 71.558, 58.899   |

All 30 no-Node processes passed with a file blocking the cache directory and no
other HOME files. R2 filters Node/Bun directories from PATH rather than physically
uninstalling tooling. R3 also fails collection if either executable remains
resolvable in that runtime environment. Writes outside HOME and read-only payload
operation remain unverified. Windows `LongPathsEnabled` is **1**; observed
quarantine-tree maxima are A **103**, B **180** characters, not deliberate deep-path
or MAX_PATH tests. No numeric size/timing budget was specified by #562.

## R2 quarantine and signatures

The exact absolute argv and complete outputs are in the corresponding native
JSON's `quarantine.commands`. In the commands below, `ENTRY` denotes A's `spike`
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

The final scanner line for A is:

```text
Scanning C:\Users\RUNNER~1\AppData\Local\Temp\spike-measure-3isctsbo\quarantine-ts found no threats.
```

B has the identical line ending in `quarantine-py found no threats.`
Both scans have empty stderr. Both direct CreateProcess launches exit **0** and
pass the golden/tree checks. This is a clean **custom scan**, with the engine
service enabled, not real-time endpoint protection approval. MotW was set/read on
the entry executable only. Shell/SmartScreen reputation enforcement, organizational
signing policy and third-party EDR remain unknown for both variants. Linux has no
macOS/Windows security observation; it remains unverified for third-party EDR too.

## Dispatch and revision boundary

Workflow **403362287** is already registered from PR runs. The parent's authorized
`workflow run install-plane-spike.yml --ref research/562-install-plane-spike`
succeeded, and independent GET confirmed genuine `workflow_dispatch`
[run 41290059704][dispatch] at exact R2 head `1e5bdc7`. A main-file contents GET 404
did **not** prevent dispatch; no bootstrap issue or registration PR is needed.
Inspection confirms **completed / success**, event `workflow_dispatch`, exact
source/expected R2 head and clean checkout on all **12** retained JSONs in its
[six evidence artifacts](https://github.com/lgtm-hq/ai-skills/actions/runs/41290059704#artifacts).
All ten registry/no-Node results pass. Linux/macOS offline again gives Bun fail /
npm pass with denial proven; Windows again stops at Error 87 and verifies rule
removal without a restricted probe/install. Dedicated Linux remains unverified.
This meets the green dispatch collection/link criterion at R2, without changing
any scenario failure or unknown above. It predates the R3 source fixes.

R3 adds bounded LIMIT+1 reads before parsing/hashing in both runtimes, non-ASCII tar
header rejection, fail-closed source identity checks, actual no-Node resolution
checks, reused-tarball checks, explicit Verdaccio process-group/tree shutdown with
bounded graceful/forced reap evidence, and clearer scan/setup statuses. POSIX
server-PID runtime output is collected when available; launcher flags and warnings
alone do not certify the complete server tree. Unit tests and a harmless local
child-tree probe validate boundaries without installing a registry dependency tree.
None of those local checks retroactively validates R2 or supplies new hosted data.

## Recommendation and concrete remaining work

**Defer the runtime decision; retain Proposed.** The existing Python-first escape
hatch requires complete comparable private-registry, no-Node and offline evidence
for both clients on every target. Identical Bun failures do not establish equal
deployability, and Windows offline is unknown. Unknown security/Harden Runner
results establish no equality either. Footprint differences have no supplied
threshold and cannot select a runtime after the fact. No criterion or owner
approval is invented here.

The parent can finish the remaining work in this order:

1. Push/review R3 and inspect fresh hosted Windows program identities, successful
   rule creation, matched denial probe, both installs and verified removal. Keep
   R2 Windows offline unverified until that evidence exists.
2. Reproduce the identical Bun local-file selection failure in a scoped transport
   experiment; a direct platform-tarball control may isolate payload deployability
   but must not replace the required wrapper/client cell. Obtain an explicit
   disposition of this known failure against deployment requirements.
3. Establish a valid same-host positive/negative control for empty-allowlist Harden
   Runner, or obtain an explicit disposition of that unmet criterion. Preserve the
   first-step restriction; do not silently add application endpoints.
4. Obtain concrete signing/security requirements for the observed signature
   failures and unknown shell/EDR scope; inspect fresh R3 dispatch evidence after
   the parent's next authorized collection.
   Apply the existing rule only when these observations and dispositions support
   it; then update ADR/index together and reconcile #566/#567/#578/#386.

Golden/closure CI, publication exclusion, green R2 dispatch, the ten-case comparison, footprint,
and exact security observations are recorded. A final accepted/revised ADR,
Windows restricted result, Harden Runner proof/disposition and security disposition
remain acceptance gaps. This revision does not close #562 or choose a runtime.

[r2]: https://github.com/lgtm-hq/ai-skills/actions/runs/41288233178
[artifacts]: https://github.com/lgtm-hq/ai-skills/actions/runs/41288233178#artifacts
[ci]: https://github.com/lgtm-hq/ai-skills/actions/runs/41288233753
[dispatch]: https://github.com/lgtm-hq/ai-skills/actions/runs/41290059704
