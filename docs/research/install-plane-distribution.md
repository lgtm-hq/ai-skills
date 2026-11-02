# Install-plane distribution experiment (#562)

Date: 2026-11-01. **Decision: one bundled Python engine behind a thin strict
TypeScript npm launcher. ADR 0008 is Accepted.** Both candidates pass the required
private-registry, no-Node and direct-plus-npm offline comparison on all five native
targets. This applies the existing Python-first tie rule; no consumer Python
installation is required. The prototypes remain research, outside the published
npm `files` allowlist, and contain no authored JavaScript.

## Method and binding policy

[A / TypeScript and B / Python](../../research/install-plane-spike/README.md)
verify the same SHA-256 USTAR fixture, subtract a capability, reject broken retained
closure and write identical golden bytes under a disposable HOME. A is a native
`bun build --compile` executable. B is the full uv-managed
python-build-standalone directory, invoked with `-I -B`: a conservative untrimmed
baseline that includes its interpreter, needs no pip/uv/consumer Python, performs
no extraction or runtime fetch, and preserves licenses. Symlinks are dereferenced
for npm transport. Production redistribution still needs its license audit.

Pins are Bun **1.4.0**, uv **0.11.26**, CPython **3.14.6**, Verdaccio **6.2.0**.
Local Python 3.14.7 tests are not the hosted measurement. Every cell uses fresh
HOME/config/temp/client caches. Verdaccio is primed during setup and has no uplinks;
registry configuration does not itself firewall clients. Both Bun and npm install
scripts-free wrappers and optional `os`/`cpu` payload packages with
`--ignore-scripts`, then verify platform selection, transported bytes/modes and
golden execution. Owned-server cleanup is part of registry acceptance.

The [owner offline decision][owner-offline] makes standalone execution primary
(no install step), with an **npm-only local-file wrapper fallback**. The Python
directory is compared by the same direct-run criterion. Both direct and npm must
pass per target/variant. Bun local-file failure remains evidence outside this gate;
[oven-sh/bun#47640][bun-upstream] tracks it. Registry installs still require both
clients. The [owner security decision][owner-security] requires unsigned command
observations and documented signing needs, not paid signing or fleet approval.

## Inspected evidence and unchanged executable source

The green [PR run 41332673633][final-pr] and genuine green
[workflow_dispatch 41332723822][final-dispatch] execute exact clean
[source fb4d21bbc68579606a283afa69af3eee664dab61][final-source]. All **24 unique
schema-3 result JSONs** were read: twelve per run, ten native (five targets × two
variants) plus two dedicated offline. Each has matching source/expected head,
empty source status, the exact event/run URL and attempt **1**. SHA-256 values
below identify the unchanged raw documents. Build/acquisition records are setup
evidence, not extra result cells; a green workflow alone is not scenario proof.

| Target / runner                   | PR artifact                                                                                        | Dispatch artifact                                                                                  |
| --------------------------------- | -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| linux-x64 / ubuntu-24.04          | [13093629541](https://github.com/lgtm-hq/ai-skills/actions/runs/41332673633/artifacts/13093629541) | [13093893911](https://github.com/lgtm-hq/ai-skills/actions/runs/41332723822/artifacts/13093893911) |
| linux-arm64 / ubuntu-24.04-arm    | [13093609553](https://github.com/lgtm-hq/ai-skills/actions/runs/41332673633/artifacts/13093609553) | [13094072632](https://github.com/lgtm-hq/ai-skills/actions/runs/41332723822/artifacts/13094072632) |
| darwin-arm64 / macos-15           | [13093637879](https://github.com/lgtm-hq/ai-skills/actions/runs/41332673633/artifacts/13093637879) | [13093853917](https://github.com/lgtm-hq/ai-skills/actions/runs/41332723822/artifacts/13093853917) |
| darwin-x64 / macos-15-intel       | [13094033451](https://github.com/lgtm-hq/ai-skills/actions/runs/41332673633/artifacts/13094033451) | [13093899143](https://github.com/lgtm-hq/ai-skills/actions/runs/41332723822/artifacts/13093899143) |
| windows-x64 / windows-2025        | [13094420287](https://github.com/lgtm-hq/ai-skills/actions/runs/41332673633/artifacts/13094420287) | [13093114706](https://github.com/lgtm-hq/ai-skills/actions/runs/41332723822/artifacts/13093114706) |
| dedicated / linux-empty-allowlist | [13094305844](https://github.com/lgtm-hq/ai-skills/actions/runs/41332673633/artifacts/13094305844) | [13094460630](https://github.com/lgtm-hq/ai-skills/actions/runs/41332723822/artifacts/13094460630) |

Native artifacts contain `results/<target>-{ts,py}.json`; dedicated artifacts
contain `linux-x64-{ts,py}-offline.json`. Collector source identity and independent
payload provenance are different: `payload_source_identity` stays **unverified**.

The successor `7909883621f726eb26806f23ab075b91c6153064` moves tests and adds
trigger logic. A diff of the executed prototype/collector/build inputs against
`fb4d21b` produces only `scripts/test-ci.sh`, whose sole change is pytest paths:

```text
git diff fb4d21bbc68579606a283afa69af3eee664dab61 7909883621f726eb26806f23ab075b91c6153064 -- research/install-plane-spike/py research/install-plane-spike/ts research/install-plane-spike/fixtures research/install-plane-spike/settings.json research/install-plane-spike/scripts scripts/tool-versions.sh
-  pytest -o addopts='' tests/test_install_plane_spike.py tests/test_install_plane_collector.py
+  pytest -o addopts='' research/install-plane-spike/tests/ \
+  tests/test_install_plane_parity.py
```

Excluding that harness-only script gives an empty diff. Workflow comparison changes
triggers/job conditions and adds `changes`, without changing native build/measure
steps, dedicated restriction, tool pins or targets. This documentation/main
integration also leaves those executed inputs unchanged. Thus these results
support the runtime decision for unchanged source; they are not relabeled as new
runs or new byte measurements. Source equivalence does not claim rebuilt archive
hashes or timings would be identical. Dispatch **41335569949** is separately associated
with exact `7909883` and completed **SUCCESS**. Its twelve actual schema-3 JSONs
were independently checked for source/expected head, clean source, event/run and
attempt 1, and their digests are recorded below. All ten native cells pass both
registry clients, no Node, direct offline and npm fallback. The two dedicated
Harden Runner results and independent payload provenance remain **unverified**.
This is separate evidence; the historical `fb4d21b` comparison above is unchanged.

| JSON                      | Artifact                                                                                           | SHA-256                                                            |
| ------------------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| darwin-arm64-py.json      | [13094489784](https://github.com/lgtm-hq/ai-skills/actions/runs/41335569949/artifacts/13094489784) | `c2775a1905e9f30a14bc91f80ef5c25bed6cef86e525d8221c06410fc8687435` |
| darwin-arm64-ts.json      | [13094489784](https://github.com/lgtm-hq/ai-skills/actions/runs/41335569949/artifacts/13094489784) | `b69beed944d959824e9a38688ef9d27410c600eccd5119ae93f6fef85ff53df0` |
| darwin-x64-py.json        | [13094894240](https://github.com/lgtm-hq/ai-skills/actions/runs/41335569949/artifacts/13094894240) | `0dac63df579ed947c56383f6b3a37c4c886eb6ccccd1b0a786dc92bd3d0de5ee` |
| darwin-x64-ts.json        | [13094894240](https://github.com/lgtm-hq/ai-skills/actions/runs/41335569949/artifacts/13094894240) | `dc4642e50b69c9268f5918a7d285e5b797787cb1da80ad2b7dad6efc23c065b6` |
| linux-arm64-py.json       | [13095216667](https://github.com/lgtm-hq/ai-skills/actions/runs/41335569949/artifacts/13095216667) | `d4d5b2447850d15eb1fb30cc35e3609483e40a716ff050577d248faa5b6bbdf3` |
| linux-arm64-ts.json       | [13095216667](https://github.com/lgtm-hq/ai-skills/actions/runs/41335569949/artifacts/13095216667) | `0ed1401d4658fb31875ea53f41c48198820bae5c2dc74d7b01dca64450c39f6e` |
| linux-x64-py.json         | [13095228033](https://github.com/lgtm-hq/ai-skills/actions/runs/41335569949/artifacts/13095228033) | `f44b65ebda11acf8609ef04591b76922500190ea92bfeec8f0c6ace71204a7d5` |
| linux-x64-ts.json         | [13095228033](https://github.com/lgtm-hq/ai-skills/actions/runs/41335569949/artifacts/13095228033) | `cbb78193e30604f15b7a32cf611a6ca1ea4a9f7cbef609d919e0e5b1be1e3322` |
| linux-x64-py-offline.json | [13095591042](https://github.com/lgtm-hq/ai-skills/actions/runs/41335569949/artifacts/13095591042) | `34b0e19456f3d6fb64b15b1a84f074e1d0a49cf0792677c308fc0480479dc5cb` |
| linux-x64-ts-offline.json | [13095591042](https://github.com/lgtm-hq/ai-skills/actions/runs/41335569949/artifacts/13095591042) | `3fca78cd1a0b3237ec307d419844ebdf3d514030bd15e6930284844aca23535b` |
| windows-x64-py.json       | [13095635752](https://github.com/lgtm-hq/ai-skills/actions/runs/41335569949/artifacts/13095635752) | `da59d0818888c02fc431c50df4c414253c6846f33dc1127cadf2971513e52822` |
| windows-x64-ts.json       | [13095635752](https://github.com/lgtm-hq/ai-skills/actions/runs/41335569949/artifacts/13095635752) | `b24bc2d74391d3c595d861bff90123f84c7a30464a0a1c19fe0b7589925285a9` |

The #614 hardening changes prototype/collector code after these runs. These
historical results certify only their bound source, not the modified #614 head;
new offline regressions establish guards, not fresh native measurements.

## Required native comparison

P = pass, F = fail, U = unverified. Each row is independently present in **both**
runs; registry columns read `private_registry.clients`, fallback columns read
`offline.installation_observation.clients`. Offline overall requires direct and
npm plus proven restriction. The Bun F is platform-selection failure, retained
as informational under the owner decision.

| Target       | Variant | Registry Bun / npm / overall | No Node | Direct offline | npm fallback | Bun local file | Offline overall |
| ------------ | ------- | ---------------------------- | ------- | -------------- | ------------ | -------------- | --------------- |
| linux-x64    | A       | P / P / P                    | P       | P              | P            | F              | P               |
| linux-x64    | B       | P / P / P                    | P       | P              | P            | F              | P               |
| linux-arm64  | A       | P / P / P                    | P       | P              | P            | F              | P               |
| linux-arm64  | B       | P / P / P                    | P       | P              | P            | F              | P               |
| darwin-arm64 | A       | P / P / P                    | P       | P              | P            | F              | P               |
| darwin-arm64 | B       | P / P / P                    | P       | P              | P            | F              | P               |
| darwin-x64   | A       | P / P / P                    | P       | P              | P            | F              | P               |
| darwin-x64   | B       | P / P / P                    | P       | P              | P            | F              | P               |
| windows-x64  | A       | P / P / P                    | P       | P              | P            | F              | P               |
| windows-x64  | B       | P / P / P                    | P       | P              | P            | F              | P               |

Both clients select only the target package in registry installations; payload
hashes/modes and golden bytes agree, and owned cleanup passes (including Windows
Job Object empty membership, reap and handle close). No-Node removes Node/Bun
paths and aliases, checks their absence, and preserves an unchanged nonsymlink
cache blocker with no other HOME files. This does not survey writes elsewhere.
Bun local-file installations select all five platform packages even in the
unrestricted same-tarball control. npm selects only the target before/during
restriction with `--offline --ignore-scripts --no-audit --no-fund` and registry
`http://127.0.0.1:9`. Direct execution precedes wrapper packing/installation.

### Restriction controls, read from raw commands

- **Linux x64 and arm64, both variants and both runs:** same-endpoint IPv4
  `connected` before restriction, then actual `stage=connect`, `errno=13`,
  `[Errno 13] Permission denied`. One owned namespace has loopback plus the
  `1.1.1.1/32 dev lo` route and IPv4/IPv6 `ip rule ... priority 1 prohibit`.
  Probe and worker share the namespace/identity prefix: `sudo -n ip netns exec`,
  `setpriv --reuid 1001 --regid 1001 --clear-groups --bounding-set=-all`,
  `--inh-caps=-all --ambient-caps=-all --no-new-privs -- env -i`.
  Worker identity is nonroot,
  `groups=[]`. Namespace deletion exits 0 and absence is read back. This is
  kernel permission denial, not route-loss errno 101 or Harden Runner-only proof.
- **macOS arm64 and x64:** connected IPv4 then actual connect EPERM/errno 1,
  `[Errno 1] Operation not permitted`, in the shared sandbox covering probe,
  direct payload and installers. Both variants' golden executions pass.
- **Windows, four variant/run cells, 20 matched program-control pairs:** identical
  resolved executable paths and SHA-256 before/during rules for `direct-ts`,
  `npm-ts`, `direct-py`, `npm-py` and `npm-node`. All IPv4 baselines connect.
  A's direct and installed executable record native Winsock
  `raw_error={api: SO_ERROR, code: 10013}`, `cleanup_errors=[]`; B's actual
  connect errors retain `winerror=10013`, `errno=13`. The exact npm Node launcher
  records `code=EACCES`, `errno=-4092`, `syscall=connect`, not a native Winsock
  observation. `npm_launcher_matches_control=true`. Exact rule deletion/readback
  exits 0 with `rules absent` in both runs. Setup, socket cleanup, mismatched
  paths/bytes, unavailable controls and timeouts cannot establish denial.

Unreachable IPv6 lacks a connected baseline and remains informational/inconclusive;
it never supplies denial proof. Historical errno 101/refusal outcomes below are
unchanged and are not current passes. The two dedicated first-step Harden Runner
results in each run remain **U**, including direct offline: no same-host
unrestricted interval exists. Their npm execution observations pass and Bun
selection fails; neither observation proves that separate restriction.

## Measured footprint

Values are computed from **PR 41332673633** raw `footprint` fields only. Times are
all three fresh-process seconds multiplied by 1000 and rounded to three decimals;
page caches were not flushed, so disk-cold time remains U. The dispatch has its
own timings/archive hashes, never substituted here. A includes its diagnostic
network entry point; these are spike payloads, not production size predictions.

| Target       | Variant | Payload bytes | Files | Archive bytes | Three fresh-process times (ms) |
| ------------ | ------- | ------------- | ----- | ------------- | ------------------------------ |
| linux-x64    | A       | 82,562,787    | 4     | 36,595,542    | 27.000, 25.505, 25.919         |
| linux-x64    | B       | 205,564,886   | 4,765 | 73,266,665    | 38.248, 39.032, 37.516         |
| linux-arm64  | A       | 82,506,259    | 4     | 36,590,069    | 22.454, 21.443, 22.356         |
| linux-arm64  | B       | 157,367,571   | 4,765 | 58,606,008    | 36.409, 35.872, 35.104         |
| darwin-arm64 | A       | 63,937,805    | 4     | 25,899,310    | 41.181, 22.571, 42.140         |
| darwin-arm64 | B       | 107,771,282   | 1,898 | 43,357,073    | 45.275, 45.390, 58.515         |
| darwin-x64   | A       | 70,731,707    | 4     | 28,468,009    | 81.406, 89.161, 84.630         |
| darwin-x64   | B       | 110,137,770   | 1,898 | 43,403,973    | 97.629, 103.755, 103.361       |
| windows-x64  | A       | 88,844,827    | 4     | 39,808,597    | 57.697, 36.869, 39.279         |
| windows-x64  | B       | 65,664,753    | 3,163 | 22,732,309    | 73.030, 57.786, 57.807         |

No writable cache inside HOME was observed with the blocker intact; arbitrary
outside-HOME writes and read-only runtime operation are U. Windows
`LongPathsEnabled=1`; observed quarantine paths are A 103 and B 180 characters,
not deliberate long-path stress. B costs more bytes/files on POSIX and fewer
bytes on Windows. No accepted size, count or timing budget exists.

## Unsigned security observations and signing needs

These are **PR 41332673633** command results, checked against the raw
`quarantine.commands`. The dispatch records its own observations. `TREE` denotes
that cell's disposable `quarantine-ts` or `quarantine-py` directory; `ENTRY` is
A's `spike` (`spike.exe`) or B's `runtime/bin/python3` (`runtime/python.exe`).
The commands below retain exact executable/flag sequences, with those path
substitutions only. Complete absolute argv and stdout/stderr remain in the
public artifacts above; table cells explicitly quote excerpts after path prefixes.

```text
/usr/sbin/spctl --status
  exit 0; stdout: assessments enabled
/usr/bin/xattr -r -w com.apple.quarantine '0083;67240000;InstallPlaneSpike;' TREE
  exit 0; empty stdout/stderr
/usr/bin/xattr -p com.apple.quarantine ENTRY
  exit 0; stdout: 0083;67240000;InstallPlaneSpike;
/usr/sbin/spctl --assess --type execute --verbose=4 ENTRY
/usr/bin/codesign --display --verbose=4 ENTRY
/usr/bin/codesign --verify --deep --strict --verbose=4 ENTRY
```

| Target / variant | `spctl --assess` exit / stderr excerpt                         | `codesign --display` exit / stderr excerpt                           | `codesign --verify` exit / stderr excerpt                      |
| ---------------- | -------------------------------------------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------- |
| darwin-arm64 A   | 1 / `invalid signature (code or signature have been modified)` | 0 / `Signature=adhoc`, `TeamIdentifier=not set`                      | 1 / `invalid signature (code or signature have been modified)` |
| darwin-arm64 B   | 3 / `rejected`                                                 | 0 / `Signature=adhoc`, `TeamIdentifier=not set`                      | 0 / `valid on disk`, `satisfies its Designated Requirement`    |
| darwin-x64 A     | 1 / `invalid signature (code or signature have been modified)` | 0 / `Authority=Developer ID Application: Jarred Sumner (7FRXF46ZSN)` | 1 / `invalid signature (code or signature have been modified)` |
| darwin-x64 B     | 3 / `rejected`, `source=no usable signature`                   | 1 / `code object is not signed at all`                               | 1 / `code object is not signed at all`                         |

All four marked direct CLI commands exit 0 with golden stdout/bytes and empty
stderr: `ENTRY TREE/fixtures fixture:drop` for A,
`ENTRY -I -B TREE/prototype.py TREE/fixtures fixture:drop` for B. A's inherited
signature metadata is invalid for the compiled bytes; B's arm64 ad-hoc signature
verifies but fails assessment. Neither passes Gatekeeper distribution assessment
or demonstrates Finder behavior.

Windows uses `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.EXE
-NoProfile -NonInteractive -Command` for these exact PowerShell expressions:

```text
Get-MpComputerStatus | ConvertTo-Json -Depth 4
  exit 0; selected output: AMServiceEnabled=true, AntivirusEnabled=true,
  RealTimeProtectionEnabled=false, IoavProtectionEnabled=false,
  BehaviorMonitorEnabled=false
Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled | Select-Object LongPathsEnabled | ConvertTo-Json
  exit 0; output: { "LongPathsEnabled": 1 }
$ErrorActionPreference='Stop'; Set-Content -LiteralPath ENTRY -Stream Zone.Identifier -Value "[ZoneTransfer]`nZoneId=3"; Get-Content -LiteralPath ENTRY -Stream Zone.Identifier
  exit 0; stdout:
[ZoneTransfer]
ZoneId=3
Get-AuthenticodeSignature -LiteralPath ENTRY | Format-List *
  exit 0; excerpt: Status : NotSigned; SignatureType : None; IsOSBinary : False
C:\ProgramData\Microsoft\Windows Defender\Platform\CurrentVersion\MpCmdRun.exe -Scan -ScanType 3 -File TREE
  exit 0; stdout:
Scan starting...
Scan finished.
Scanning TREE found no threats.
```

`MpCmdRun.exe` is invoked directly, not as a PowerShell expression. For this PR,
`TREE` is `C:\Users\RUNNER~1\AppData\Local\Temp\spike-measure-sag4pk8a\quarantine-ts`
or `quarantine-py`. Both direct CreateProcess launches exit 0, pass golden/tree
checks and have empty stderr. MotW is set/read on the entry only, not every runtime
file. Defender's custom scan is clean with real-time, IOAV and behavior protection
disabled. SmartScreen shell/reputation enforcement and organization-managed fleet
policy remain U. Linux has no native quarantine equivalent; third-party EDR is U.

For a signed Mac route, A needs the **final** compiled Mach-O signed with Developer
ID Application, hardened runtime and reviewed Bun/JIT entitlements. B needs nested
Mach-O extensions/dylibs and its interpreter signed inside-out with reviewed
entitlements. Notarize the final archive/container using `notarytool`, assess the
distributed output with `spctl`, and test Finder behavior. Bare executables and
zip/directory bundles cannot receive stapled tickets; supported pkg/app/dmg
containers can. Exact entitlements, notarization/stapling and signed verification
belong to human-secret-gated [#619](https://github.com/lgtm-hq/ai-skills/issues/619).
Both Windows variants need Authenticode for a signed route; this is cost-gated
[#618](https://github.com/lgtm-hq/ai-skills/issues/618), and reputation remains
separate. No paid signing or third-party EDR experiment is required for #562.
Free checksums, GitHub artifact attestations, SLSA provenance, npm provenance and
Sigstore/cosign keyless signing remain required in production. Where paid signing
is unavailable, deliver **unsigned but attested**. This spike implements no
production attestation pipeline and claims no fleet approval.

## Decision, downstream reconciliation and limits

The [merged ADR escape hatch][merged-escape] gives the Python-first tie rule:
when B is equally deployable under required private-registry/no-Node/offline
restrictions, choose a single Python engine behind a thin TypeScript npm launcher.
All ten native cells pass those restrictions in both inspected runs, so **apply
that branch and accept revised ADR 0008**. Smaller POSIX A footprint does not invent
a budget or override the rule. The selected self-contained Python bundle supplies
the standalone primary offline route; no consumer Python is required.

The semantic build/install boundary remains: only build may resolve; install
verifies embedded resolved metadata, subtracts and enforces closure/denies without
resolving or fetching missing inputs. Both live in one typed Python package.
Strict TypeScript is the npm launcher and has no duplicate engine semantics.

Downstream reconciliation is required #562 work before implementation:

| Issue | Effect of this decision                                                                                                                                                      | Retained constraints                                                                                                                  |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| #566  | Migrate authored JS to strict TS; final role is a thin npm launcher selecting/invoking the Python payload. Replace Bun-compiled engine targets with bundled-runtime handoff. | Behavior/CLI golden parity, test count/coverage, typecheck, no authored JS, required gateway CI.                                      |
| #567  | Extract the typed Python package as the common engine for build and install; subsequent work adds install commands there.                                                    | Behavior-preserving extraction, old shims/flags, mypy strict, `py.typed`, generated-byte parity and wheel import.                     |
| #578  | Implement artifact verification, subtraction, closure/deny evaluation and consumer profiles in Python; TS delegates.                                                         | Digest/schema failure before writes, multi-hop origin deny, stale selector/frozen/profile behavior, no install resolution or network. |
| #386  | Distribute artifacts plus per-platform self-contained Python bundles; TS npm wrapper, direct offline primary and npm local-file fallback.                                    | Byte/digest identity, private mirrors, both registry clients, no bootstrap, license/notice and owner attestation/signing policies.    |

Replacement bodies and explanatory implementation-prompt corrections are prepared
from fresh issue bodies/comments for the parent to apply and independently read
back. This local pass makes no remote issue/comment edits. All unrelated criteria
and owner policies remain binding, including no authored JS/strict TS and the
free-attestation, #619 human-secret and #618 cost gates.

**Remaining U:** dedicated first-step Harden Runner without a same-host baseline;
independent payload-source binding (native hashes are not independently verified,
transferred archives are not bound to expected build metadata); Finder/SmartScreen
and fleet enforcement; deliberate long paths; read-only runtime/outside-HOME
writes; disk-cold timing; non-AVX2, musl and older-OS compatibility. Unverified
never certifies. These are disclosed runner limits, not extra universal-green
gates on the required native comparison. Production provenance remains required.
Optional spike hardening belongs to #614 under [the owner review cap][owner-cap].
No production engine or paid signing implementation is added by #562.

## Raw result identity manifest

Hashes are SHA-256 of the actual result JSON bytes, not archive/build digests.
Artifact links above are scoped to the exact run; N = native, H = dedicated
Harden Runner. A = `ts`, B = `py`; result filenames follow the table above.

| Run         | Scope | Target       | Variant | Raw JSON SHA-256                                                   |
| ----------- | ----- | ------------ | ------- | ------------------------------------------------------------------ |
| 41332673633 | N     | darwin-arm64 | B       | `001ce23b450caf9051dff79270cfffead036b0eb227d822e70337dea21f8e54d` |
| 41332673633 | N     | darwin-arm64 | A       | `70362967efe4846aa04e8180dd8b3c6e05f943cb72e2533130be3be95f63759d` |
| 41332673633 | N     | darwin-x64   | B       | `428c2fd848ff51be466de84e4e0eca07b58ab37f9ef46fcb59432b980b2192d8` |
| 41332673633 | N     | darwin-x64   | A       | `729ff654b9a29dd81306878f10fbda08a17c36dea84e92023ae6de433af1b172` |
| 41332673633 | N     | linux-arm64  | B       | `ad54d0e862ef24d1b4f9efdbcfc8152cf56edd3fc75e1306b2cde838eb87d7a6` |
| 41332673633 | N     | linux-arm64  | A       | `4209debd725bb384e7330af5b50a4266cb6d29a2cba3879c5315c026de45bcf4` |
| 41332673633 | N     | linux-x64    | B       | `c866738aa4a91c92123d1767e7622d6204ff3b8be6fcdef7403352f6d7a2762b` |
| 41332673633 | N     | linux-x64    | A       | `83d3ef8f6b0c193168231a6d65cba7c09b9c527e39312072b00496268f281684` |
| 41332673633 | N     | windows-x64  | B       | `9388524948bf707f44122472a157bbaa753a9b0d0c3e3f90c2525195f040c301` |
| 41332673633 | N     | windows-x64  | A       | `e65924e2973b21ac5da7295f111036f99356d46288ed19f37bc6b95c6b283e0a` |
| 41332673633 | H     | linux-x64    | B       | `1baabe6b12fd3560b307578ce13efc42a0956b323879100ea4d44c7b040690ac` |
| 41332673633 | H     | linux-x64    | A       | `90b3664e80c7376955cfe63b33e85575d3ebaddba22b5b62c1797d48b61ca3a5` |
| 41332723822 | N     | darwin-arm64 | B       | `e0b72c2c21cc7e49299f4c7ac765b56f032f19ee2385a6494d92c06caf5c0693` |
| 41332723822 | N     | darwin-arm64 | A       | `1c712862f80e08e31afb99669966b4716041a7018a135997ed3cec76e609a60f` |
| 41332723822 | N     | darwin-x64   | B       | `542e87c9d02cde2b6a03725b4a10fdd5faca0f73ab34f40b8c125360f14d263c` |
| 41332723822 | N     | darwin-x64   | A       | `228c75dce4cadd2840f09fac7415a94b58b40ace20596edc9488900a9e982322` |
| 41332723822 | N     | linux-arm64  | B       | `68583b60a864b9941c27edeb9b6f5430c6363ce5a2527904a2f6d4a17b2b7619` |
| 41332723822 | N     | linux-arm64  | A       | `8479039219853cb778bbc58770e2d00bff0f22afdea8e044644ea9d3c7034697` |
| 41332723822 | N     | linux-x64    | B       | `3ab591549565677b39a2ef81b63e22a5ccd2c8303ab2e2f96d96d9673675a283` |
| 41332723822 | N     | linux-x64    | A       | `df231ce92e40f393a410df2c475934715d5e2241a1e4ef8a11345c02257851da` |
| 41332723822 | N     | windows-x64  | B       | `40c36456a8dacb66bcb4b286c32f732a7aef26ca5402188caba7108922469edf` |
| 41332723822 | N     | windows-x64  | A       | `3addd5b3c6aa2795353d74c06a33f7d8b8d497fbeefdd42f92827a29eef60397` |
| 41332723822 | H     | linux-x64    | B       | `52cf3def2be738f6bd7ae01882e4cda87629fcbcea9a4beaedea1073e53cf33b` |
| 41332723822 | H     | linux-x64    | A       | `af7129c1d2ee08898165c926acd9de3fa92ec09bbb2b52b447b4be8d1ada922d` |

## Historical observations

The [earlier report snapshot](./install-plane-distribution-history.md) preserves
raw links, measurements and the correction history. Its Proposed statuses and
future-work statements describe the named earlier revisions, not this decision.
Old policy/classifier outcomes remain intact; unreachable or refusal never
supplies current denial proof. No historical artifact was edited or relabeled.

[final-pr]: https://github.com/lgtm-hq/ai-skills/actions/runs/41332673633
[final-dispatch]: https://github.com/lgtm-hq/ai-skills/actions/runs/41332723822
[final-source]: https://github.com/lgtm-hq/ai-skills/tree/fb4d21bbc68579606a283afa69af3eee664dab61/research/install-plane-spike
[owner-cap]: https://github.com/lgtm-hq/ai-skills/issues/562#issuecomment-6561604904
[owner-security]: https://github.com/lgtm-hq/ai-skills/issues/562#issuecomment-6557818942
[owner-offline]: https://github.com/lgtm-hq/ai-skills/issues/562#issuecomment-6557886641
[bun-upstream]: https://github.com/oven-sh/bun/issues/47640
[merged-escape]: https://github.com/lgtm-hq/ai-skills/blob/032ee309817813a9ef81bb2450cbed646a625222/docs/adr/0008-engine-runtime-build-and-install-planes.md
