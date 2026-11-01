# Install-plane distribution experiment (#562)

Date: 2026-11-01. **Evidence incomplete; ADR 0008 remains Proposed.** This is the
throwaway distribution experiment after #561/#613, not the M6 engine. Revision 2
repairs failures observed in PR-head collection; live acceptance remains pending.

## Method and scope

[Sources and reproduction](../../research/install-plane-spike/README.md) include:

- One generated, data-only USTAR fixture with two qualified capability IDs,
  closures, archive/file SHA-256 values and golden output after subtracting one ID.
  The retained file starts with a UTF-8 BOM; tests compare actual installed bytes
  with the verified digest. Scoped Git attributes preserve fixture bytes on Windows.
- Strict TypeScript compiled with `bun build --compile` for native `darwin-arm64`,
  `darwin-x64`, `linux-x64`, `linux-arm64`, and `windows-x64` targets.
- Stdlib-only Python bundled as the entire uv-managed python-build-standalone
  directory. No self-extractor, consumer Python, uv, pip or runtime fetch is needed.
  Python runs with `-I -B`. Symlinks are dereferenced because npm pack omits them.
  Keeping the full tree is a conservative untrimmed baseline, not a minimum Python
  footprint. Runtime licenses remain in the tree; redistribution needs its own audit.

Both prototypes validate the complete inventory before writes, including excluded
files. They reject reserved Windows device basenames, case aliases, directory case
aliases and file/directory collisions. They reject missing/removed closure entries.
The co-located index is **not authenticated**: hashes detect corruption, not a
maliciously replaced index and archive. Production contracts remain M6/M7 work.

Pytest parity compares the Python and Bun **source CLIs**. Bun tests and typecheck
are required by the spike workflow; `SPIKE_REQUIRE_BUN=1` makes missing Bun a failure.
Compiled TypeScript and the bundled Python runtime are exercised separately by the
collector's golden stdout **and actual written tree** checks. They are not inferred
from source parity alone.

CI uses the repository's shared uv/Bun pins. uv 0.11.26's upstream
[download metadata](https://github.com/astral-sh/uv/blob/0.11.26/crates/uv-python/download-metadata.json)
was inspected: it includes CPython **3.14.6 for all five targets**, but not 3.14.7.
The spike pin now selects 3.14.6 without changing shared toolchain pins.

## Scenario observations and limits

Private-registry setup starts a pinned cached Verdaccio using `bun x`, with no
uplinks and an explicit 512 MB request limit. A random disposable account is used
only for publication. HTTP status, JSON and token are validated. Errors retain
sanitized HTTP/server evidence; credentials never enter retained command output.
Bun and npm are separate measured install clients, each with fresh HOME, config
and caches and `--ignore-scripts`. The wrapper has exact optional platform
dependencies and no lifecycle scripts or authored JavaScript. Other platforms are
empty stand-ins. Each installed payload's SHA-256 inventory and executable bits
are compared with the build before direct execution. Installed platform packages
are inventoried; incompatible platform selection is a failure. This measures configuration
and registry traffic, not an OS firewall around the registry client.

Offline collection uses **real package-manager installations**, not a custom
Python extractor. Bun packs local wrapper and platform tarballs without scripts;
the wrapper's optional dependencies refer to those local files. Both clients use
fresh caches, local tarballs, `--offline` and `--ignore-scripts`. Before isolation,
the same tarballs are installed with identical flags and separate fresh caches as
a positive package-manager control. Both per-client and combined results remain
visible, even when the unrestricted Bun control fails platform selection. Unsupported flags,
omitted optional packages and transport differences are observed failures. npm is
an explicit consumer scenario, not this repository's development package manager.

A successful unrestricted IPv4 connection must precede explicit denial of the
**same endpoint on the same host**. IPv6 is informational. Missing routes before
isolation, unavailable tools, DROP timeouts and missing controls remain unverified.
Native Linux uses network namespaces with the original unprivileged consumer UID;
when sudo is needed to create the namespace, setpriv drops UID/GID and clears
supplementary groups before an explicit credential-free environment is restored.
The worker records actual effective identity and refuses root package managers.
Cleanup errors remain errors; persisted JSON is exported in finally.
macOS attempts `sandbox-exec`; Windows uses
per-program outbound firewall rules for the probe, package managers and installed
entry executables. These are **separate from Harden Runner**. Windows records
firewall profiles and verifies rule removal in `finally`, including partial-create
failures. The runner agent is outside the rule scope. Cleanup failure is unverified.

The dedicated Linux job starts Harden Runner block mode with an empty allowlist
as its **first step**. Probe and installers run directly under it, with no unshare
prefix. The configuration flag never counts as an observation. Starting first
means there is no unrestricted same-host baseline: this row therefore remains
**unverified**, even if the probe reports explicit denial and installation succeeds.
An independently controlled follow-up experiment is needed to establish Harden
Runner denial itself. Native namespace controls cannot establish it.

First-step block mode may prevent checkout or artifact download; in that case no
payload measurement is possible. If checkout succeeded, the runner's existing
Python exports failed acquisition as JSON; if checkout itself failed, the setup
log is the only available record. No
application allowlist is broadened to make collection green. If acquisition works,
all offline JSON is printed to the job log and step summary before a best-effort
artifact upload; blocked upload does not erase the local/log/summary evidence.
GitHub's own log/summary retention and summary size limits still apply. Built Bun
is transferred as setup data; npm comes from the runner. No tooling fetch belongs
to the measured interval. Native Linux payload upload uses an explicit status
condition plus successful build outcome, so later measurement errors cannot hide
usable archives from the independent job.

No-Node control removes PATH directories containing Node/Bun, retaining Windows
loader variables, PATHEXT and disposable AppData locations. Neither tool is
physically uninstalled. Footprint records bytes, files, three fresh-process times
and HOME cache writes with an unavailable cache directory. OS caches are not
flushed; writes outside HOME and read-only payload operation remain unverified.

## Platform security collection

Harden Runner v2.22.3 supports only audit mode on hosted macOS/Windows; see its
[compatibility matrix](https://github.com/step-security/harden-runner/blob/46b06cea07f9e64621fdf066ba77ac6915163d43/README.md#environment-compatibility-matrix).
Audit mode does not prove denial.

macOS records recursive quarantine xattrs, `spctl --status`, exact
`spctl --assess --type execute --verbose=4`, `codesign --display --verbose=4`,
`codesign --verify --deep --strict --verbose=4` and direct CLI execution outputs.
Disabled/unavailable Gatekeeper remains unverified. CLI launch alone does not
prove Finder/Gatekeeper enforcement, notarization or organizational signing needs.

Windows records `Get-MpComputerStatus`, exact `MpCmdRun -Scan -ScanType 3 -File`
output, Authenticode status, `LongPathsEnabled`, and the actual longest installed
path. Clean requires an enabled engine and explicit no-threat output. Threat
requires matching threat output; service/engine errors and inconclusive return
codes are unverified. `Zone.Identifier` is set/read on the entry executable only,
not the whole Python tree. Direct CreateProcess does **not** exercise MotW shell
or SmartScreen enforcement. That enforcement, reputation, signing requirements
and third-party EDR remain unverified for both variants.

The longest observed path does not prove deliberately deep/MAX_PATH behavior.
Unsigned binaries, non-AVX2 Bun baseline targets, musl and older Linux systems need
separate evidence; this spike neither expands its target matrix nor extrapolates.

## Current comparison

Initial local Linux x64 exploration used Bun 1.4.3, uv 0.13.1 and CPython 3.14.7,
on Linux 7.0.0-42/glibc 2.43. These historical sizes/timings do not describe the
revised collector or the newly pinned runtime; they need fresh hosted collection.

| Initial local observation              | A: compiled TypeScript                    | B: standalone Python                      |
| -------------------------------------- | ----------------------------------------- | ----------------------------------------- |
| Unpacked bytes / files                 | 90,812,917 / 4                            | 207,917,967 / 4,966                       |
| Archive bytes                          | 41,897,811                                | 73,984,429                                |
| Three fresh process times (ms)         | 20.563, 22.017, 22.190                    | 141.109, 41.908, 42.230                   |
| Default Verdaccio publication          | HTTP 413                                  | HTTP 413                                  |
| Raised-limit Bun-only registry install | Initial functional observation            | Initial functional observation            |
| Old extraction-only offline result     | Unverified for package-manager acceptance | Unverified for package-manager acceptance |

The old network probes lacked positive controls, and the old offline worker only
extracted tar files. Their prior offline “pass” cannot satisfy #562. The old registry
run did not measure npm or verify transported payload digests. Its size-limit finding
is useful, but it cannot substitute for revision 1's full registry scenario.

The first hosted collection at source `b722c5fb5ca078c04f32b4b5d58c5422d8c00291`
is [run 41284689759](https://github.com/lgtm-hq/ai-skills/actions/runs/41284689759),
a **failed PR-triggered run**, not workflow_dispatch. Its retained
`spike-evidence-*` artifacts contain eight native Linux/macOS runtime JSONs and
two dedicated empty-allowlist JSONs. Windows produced no runtime measurements.

| R1 hosted target | Registry A/B | No Node A/B | Native offline A/B | Quarantine CLI A/B |
| ---------------- | ------------ | ----------- | ------------------ | ------------------ |
| Linux x64        | Setup failed | Pass / pass | Fail / fail        | Unverified         |
| Linux arm64      | Setup failed | Pass / pass | Fail / fail        | Unverified         |
| macOS arm64      | Setup failed | Pass / pass | Fail / fail        | Pass / pass        |
| macOS x64        | Setup failed | Pass / pass | Fail / fail        | Pass / pass        |
| Windows x64      | Unverified   | Unverified  | Unverified         | Unverified         |

Registry stderr on all four collected targets was:

```text
Could not find an existing 'verdaccio' binary to run. Stopping because --no-install was passed.
```

The collector changed TMPDIR/TEMP/TMP after build primed bun x. Revision 2 restores
and records the trusted setup temp/cache identity for the server only; measured
clients still use fresh temp/config/cache locations. The server retains
`--no-install`, no uplinks and sanitized account/publication output. Timeout during
both termination waits is retained instead of aborting later evidence.

Native offline probes demonstrated independent namespace/sandbox denial. For
**both runtimes on every collected target**, npm installed only its target platform
and passed; Bun installed **all five platform packages**, executed the matching
payload successfully, and correctly failed the incompatible-platform assertion.
R1 lacks the unrestricted installer control, so attribution to network restriction
versus Bun local-file selection needs R2 control evidence. No assertion or measured
client has been removed. Linux also failed temporary-directory cleanup after its
sudo worker created root-owned files. Windows failed locale-dependent golden/parity
reads and display-path Git attribute matching before build. Revision 2 preserves
literal BOM bytes, uses explicit UTF-8 and NUL-delimited relative attribute paths.

The two dedicated Linux JSONs record `unverified` and `denial_proven: false`, with
no unrestricted same-host control. Their Bun/npm selection observations match the
native results; successful collection does not establish Harden Runner denial.
Quarantine CLI success in the table does not establish Finder, Gatekeeper,
SmartScreen or third-party EDR enforcement.

| R1 hosted target | A bytes / files | B bytes / files     | A / B archive bytes     |
| ---------------- | --------------- | ------------------- | ----------------------- |
| Linux x64        | 82,550,499 / 4  | 205,507,842 / 4,761 | 36,592,094 / 73,245,058 |
| Linux arm64      | 82,506,259 / 4  | 157,310,523 / 4,761 | 36,586,874 / 58,582,117 |
| macOS arm64      | 63,921,293 / 4  | 107,714,226 / 1,894 | 25,896,070 / 43,333,933 |
| macOS x64        | 70,715,323 / 4  | 110,080,718 / 1,894 | 28,464,766 / 43,377,451 |

These are R1 artifacts, not predictions for repaired collection. Exact timings,
command output and source fingerprints remain in the linked run artifacts.

## Revision 2 local Linux smoke

A real local Linux x64 build used the current repository pins: Bun **1.4.0**,
uv **0.11.26**, CPython **3.14.6**, and Verdaccio **6.2.0**. The measured npm client
was **9.2.0**, with Node **22.22.1** available for setup/client tooling.
This is a dirty local
revision based on `b722c5f`, with build source fingerprints and raw commands
retained by the worker; it is not fresh hosted, Windows or macOS evidence.

The native collector's first run completed with exit 0 while truthfully recording
registry readiness failure at the old 15-second retry window. After extending the
bounded window, a separate real registry smoke reached HTTP 200 readiness,
created its disposable account with HTTP 201, published all twelve platform/wrapper
packages, and installed both variants with **both Bun and npm**. All four clients
selected only Linux x64, matched transported payload hashes/modes and executed the
golden fixture. The server used `bun x --bun --no-install verdaccio@6.2.0`, no
uplinks, and the build's setup temp/cache identity. Exact sanitized output and the
initial failure are retained; fake-process unit tests are not startup evidence.
The resolved server version is recorded, but its transitive setup tree is not
locked or claimed reproducible.

The same-host unrestricted local-file controls reproduced Bun installing all five
optional platform packages for both runtimes. npm selected Linux x64 and passed.
Under independently proven namespace denial, using **the identical tarballs**,
Bun again failed selection and npm passed. All matching native payload inventories
and executions passed. This establishes the selection problem locally without
attributing it to network denial or either runtime. Combined offline results stay
**fail**. User namespace mapping was denied; the sudo/setpriv fallback successfully
ran the restricted worker at effective UID/GID **1000/1000**, supplementary groups
empty, and cleanup completed without privileged deletion or suppressed errors.
These observations do not establish Harden Runner-only denial.

## Raw evidence and dispatch handoff

R1 hosted JSON exists as described above; no green dispatch acceptance run exists.
Each independent scenario is saved before the next begins, including collector
errors. Evidence names the
actual checked-out source SHA, expected PR head, event, run URL, commands, UTF-8
stdout/stderr, exit code and timing. Build metadata retains source fingerprints.
Inspect statuses and exact outputs; a green collection badge is not a scenario pass.

The workflow keeps `workflow_dispatch` and adds narrow `pull_request` paths for the
spike, workflow, tests and scoped attributes. It has no secrets, `contents: read`
and `persist-credentials: false`, and checks out the actual PR head. Parent can
push this revision and inspect PR-head collection **before merge**, without seeding
a workflow stub on main. Runner labels, ARM availability and Harden Runner support
still require a live run.

A PR-trigger run does **not** satisfy the explicit green `workflow_dispatch`
acceptance criterion. A new dispatch-only workflow requires default-branch
registration. Safe follow-through: inspect the PR evidence first, then let the
parent reconcile a reviewed registration path with the existing merge/evidence
hold and run dispatch at the exact reviewed ref once registered. Registration,
dispatch and any remote edits belong to the parent; no bootstrap writes are part
of this revision. The hold is not waived by adding PR coverage.

## Recommendation and decision rule

**Defer the runtime decision.** Apply the existing Python-first tie rule over
private-registry, no-Node and offline deployability on all five supported targets,
with Bun and npm separately required for each installation scenario. Private
registry must demonstrate scripts-free installation, correct platform selection,
verified bytes and execution without public uplinks. No-Node measures self-contained
execution. Offline adds identical local-tarball installer controls, fresh caches,
verified restriction and installed execution. Retain every per-client failure and
its combined variant result; a green evidence job can contain scenario failures.

Footprint records bytes, file count, timing and cache requirements as deployment
costs; no numerical size/timing budget was specified in #562. It cannot create a
new failure threshold or override Python-first equality after seeing the numbers.
An observed inability to meet a real capacity/cache restriction would bear on the
corresponding installation/execution criterion. Any additional owner requirement
must be explicit before applying it; no changed ADR outcome has been accepted.

Complete inspected observations must support B being equally deployable before
invoking the Python escape hatch. Otherwise A must be demonstrated no worse on
every core target/client criterion. Unknown core results cannot be equal or better;
identical failures are not proof of deployability and require owner disposition.
The observed R1 collector failures and absent Windows data preclude either choice.

Third-party EDR, Finder/SmartScreen, disabled Gatekeeper and empty-allowlist denial
without a baseline are separately unverified limitations, never equal or pass.
They do not supply missing core evidence, and core observations cannot establish
security approval. Native namespace/sandbox/firewall evidence is **not the issue's
requested Harden Runner-only offline proof**. That gap, the true workflow_dispatch
run, and owner deployment/security criteria remain outstanding. ADR 0008 stays
Proposed until fresh complete hosted/dispatch evidence and the owner's criteria
permit the documented rule. Parent must then reconcile #566/#567/#578/#386 and
update the ADR/index together. This revision selects neither runtime.

## Acceptance accounting

- [x] Shared golden fixture and fail-closed source tests; required PR CI gates wired.
- [x] Spike remains outside the published npm `files`; no authored JavaScript.
- [ ] Inspect repaired native hosted JSON, including both clients, every OS and variant;
      R1 Linux/macOS failures are recorded above and Windows data is absent.
- [ ] Resolve empty-allowlist collection/control limits without attributing namespace
      denial to Harden Runner or silently adding application endpoints.
- [ ] Link a green **workflow_dispatch** run and retained raw evidence.
- [ ] Record demonstrated quarantine/signing needs and all unverified scopes.
- [ ] Populate hosted comparison/footprint table and apply the evidence decision rule.
- [ ] Update ADR 0008 and its index together after evidence inspection.

These live acceptance items remain a merge hold. Local regressions validate the
collector's boundaries; they do not fabricate hosted evidence or complete #562.
