# Install-plane distribution experiment (#562)

Date: 2026-11-01. **Evidence incomplete; ADR 0008 remains Proposed.** This is the
throwaway distribution experiment after #561/#613, not the M6 engine. Revision 1
enables safe PR-head collection; it does not complete the hosted evidence gate.

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
fresh caches, local tarballs, `--offline` and `--ignore-scripts`. Unsupported flags,
omitted optional packages and transport differences are observed failures. npm is
an explicit consumer scenario, not this repository's development package manager.

A successful unrestricted IPv4 connection must precede explicit denial of the
**same endpoint on the same host**. IPv6 is informational. Missing routes before
isolation, unavailable tools, DROP timeouts and missing controls remain unverified.
Native Linux uses network namespaces; macOS attempts `sandbox-exec`; Windows uses
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

| Hosted target | Private registry A/B | No Node A/B | Offline A/B | Quarantine A/B             |
| ------------- | -------------------- | ----------- | ----------- | -------------------------- |
| Linux x64     | Unverified           | Unverified  | Unverified  | Third-party EDR unverified |
| Linux arm64   | Unverified           | Unverified  | Unverified  | Third-party EDR unverified |
| macOS arm64   | Unverified           | Unverified  | Unverified  | Unverified                 |
| macOS x64     | Unverified           | Unverified  | Unverified  | Unverified                 |
| Windows x64   | Unverified           | Unverified  | Unverified  | Unverified                 |

## Raw evidence and dispatch handoff

No green hosted run or portable hosted JSON exists yet. Each independent scenario
is saved before the next begins, including collector errors. Evidence names the
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

**Defer the runtime decision.** Missing hosted observations establish neither
cross-platform equality nor superiority. Apply ADR 0008's explicit Python escape
hatch first when B is equally deployable across the measured private-registry,
no-Node and offline restrictions; otherwise accept A only if it is no worse on
every restricted criterion. Unknown results never satisfy either branch. Parent
will reconcile the measured decision rule and downstream #566/#567/#578/#386
specifications before changing ADR status or implementing M6/M7.

## Acceptance accounting

- [x] Shared golden fixture and fail-closed source tests; required PR CI gates wired.
- [x] Spike remains outside the published npm `files`; no authored JavaScript.
- [ ] Inspect native hosted JSON, including both install clients, every OS and variant.
- [ ] Resolve empty-allowlist collection/control limits without attributing namespace
      denial to Harden Runner or silently adding application endpoints.
- [ ] Link a green **workflow_dispatch** run and retained raw evidence.
- [ ] Record demonstrated quarantine/signing needs and all unverified scopes.
- [ ] Populate hosted comparison/footprint table and apply the evidence decision rule.
- [ ] Update ADR 0008 and its index together after evidence inspection.

These live acceptance items remain a merge hold. Local regressions validate the
collector's boundaries; they do not fabricate hosted evidence or complete #562.
