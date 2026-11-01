# Install-plane distribution spike (#562)

Throwaway code, separate from the gateway and future M6 engine. See the
[report](../../docs/research/install-plane-distribution.md) for evidence and limits.
Nothing here is in the gateway's npm publication allowlist.

**Final decision:** [ADR 0008](../../docs/adr/0008-engine-runtime-build-and-install-planes.md)
is Accepted: one bundled Python engine behind a thin strict TypeScript npm
launcher. Both candidates pass the required five-target registry/no-Node/offline
comparison. The selected Python directory includes its interpreter; consumers do
not install Python, uv or pip. Direct bundled execution is the primary offline
route, with npm-only local-file wrapper installation as fallback. The TypeScript
prototype remains comparison evidence, not the production install engine.

## Contract

Both source CLIs take `FIXTURE EXCLUDE`, require a disposable `HOME`, and write
only `HOME/.spike-target`, which must not already exist. Archive/file digests,
complete portable inventories and retained closures are validated before writes.
The shared data-only USTAR fixture includes a BOM-prefixed retained Markdown file;
actual installed bytes must match its verified hash. Windows reserved basenames,
case aliases and file/directory collisions are rejected, even for excluded files.
This tiny regular-file UTF-8 profile is not the production v2 schema. Paths
are ASCII, at most **100 bytes/characters** (the USTAR name slot), and at most
**16 components**, checked before splitting or constructing directory prefixes.
Inputs are each capped at 1 MiB before parsing; Python JSON recursion errors are
controlled validation failures.
Both runtimes reject non-512-byte archive lengths, nonzero string suffixes after
NUL, nonzero prefix bytes and invalid or empty mode/uid/gid/size/mtime octal fields.
Device-number slots (devmajor/devminor) are ignored for regular files; device
entries themselves are forbidden. This is a narrow profile, not validation of
every USTAR metadata field.
Python validates raw headers, checksums, payload bounds and the zero trailer before
tarfile interpretation; even empty PAX/global/GNU extension records are rejected.

Generate fixture bytes with `scripts/fixture.py`; `--check` is its byte-drift gate.
Scoped Git attributes preserve fixture bytes and LF script lines on Windows.
No compiled executables or runtime bundles are committed.

## Local use

Use the existing repository Python environment. Before a local build, install the
selected uv-managed Python from `settings.json` with `uv python install <version>`
if it is not already available. `build.py --installed-python` deliberately refuses
to download one. Do not change a shared environment or install other OS toolchains.
Network is permitted for setup, TypeScript tooling and priming pinned Verdaccio.

```bash
unset PYTHONPATH
export UV_NO_SYNC=1
bun install --cwd research/install-plane-spike/ts --frozen-lockfile
uv run python research/install-plane-spike/scripts/fixture.py --check
uv run pytest research/install-plane-spike/tests/ tests/test_install_plane_parity.py
spike_output="${TMPDIR:-/tmp}/install-plane-562-build"
# Choose a new, absent output directory; build refuses to overwrite one.
uv run python research/install-plane-spike/scripts/build.py \
  --installed-python --output "$spike_output"
uv run python research/install-plane-spike/scripts/measure.py \
  --build "$spike_output" --results "$spike_output/results"
```

Use disposable machines for collection. Native isolation attempts namespaces,
macOS sandboxing or Windows per-program firewall rules. A same-host successful
IPv4 control is required before explicit denial proves the probe restriction;
unavailable IPv6 is informational. Unreachable, refusal and timeouts are
inconclusive. POSIX accepts EACCES/EPERM; Windows Python requires actual
`winerror == 10013`, retained alongside errno and the original error. Windows
Node retains structured EACCES from the exact selected npm launcher; this is a
Node permission result, not an observed native 10013. Linux/macOS
probe and installers share a namespace/sandbox. Historical R11 Windows controls
for A reported refusal and remain inconclusive. The final `fb4d21b` runs instead
record matched connected-to-native-10013 controls for A's direct/installed copies,
actual WinError 10013 for B and EACCES for npm's exact Node launcher. The Windows-only
controls compare the same fixed
IPv4 endpoint, argv, resolved executable path and SHA-256 before/during restriction
for direct A/B, actual npm Node and installed npm payloads. Seeded baseline copies
at future install paths are removed before real fresh installs. Windows npm uses
an explicit Node/npm-cli pair; mismatched launchers, missing/changed programs,
timeouts or failed cleanup cannot pass. A's `--spike-network-control` diagnostic
and emitted TypeScript Node module open only the fixed probe socket; normal
installation never calls them. Bun Win64 now uses a deferred `bun:ffi` Winsock
diagnostic inside that same executable; native 10013 is access-denial proof,
while refusal/unreachable/timeout stay inconclusive. Nonblocking connect/select
is bounded to two seconds. Raw native errors and cleanup failures are retained;
socket, Winsock reference and DLL cleanup are attempted, and cleanup failure
invalidates proof. Node and non-Windows keep their existing socket path. Tests
inject native/socket boundaries and never connect. The final hosted runs validate this
diagnostic at `fb4d21b`. Informational Bun is
outside this required denial scope. Exact rules, commands and cleanup are retained.
No-Node control removes tool directories from PATH while preserving Windows loader
necessities and using disposable AppData/HOME locations. Node, nodejs, Bun and
bunx resolution or unexpected HOME files fail the runtime observation. Filtering
and detection share aliases and PATHEXT suffixes. The cache blocker must remain
an unchanged nonsymlink regular file after execution; deletion, overwrite or
replacement makes the observation fail.
The installed target and every entry are checked without following symlinks.
Only the expected regular files and their required ancestor directories may exist;
unexpected empty directories and other types fail. Content reads are bounded by
golden length plus one byte. This post-execution check is not a filesystem sandbox.
Python-only pytest runs skip TypeScript cases when Bun is absent; setting
`SPIKE_REQUIRE_BUN=1` makes missing Bun fail, as required by dedicated spike CI.

## CI and raw evidence

The workflow's `changes` job compares the complete PR diff (including deleted
and renamed files) with the globs in `harness-inputs.txt`. It triggers the native
matrix whenever any harness input changes, including local imports, conftests,
shared helpers, fixtures, settings and tool/dependency pins outside the spike
directory. A small root guard test statically follows the local import and literal
file-reference closure and fails if an input lacks a trigger pattern.

The same matrix also runs nightly at 03:17 UTC, on workflow dispatch, and on every
PR whose head branch starts with `release/`, regardless of changed files. A release
PR is mergeable only with a green spike run on its current head; the orchestrator
enforces this at merge time. These runs retain the same evidence artifacts.

The workflow checks out the exact PR head (the default branch for scheduled runs)
and runs the full harness in `research/install-plane-spike/tests/` plus
`tests/test_install_plane_parity.py` on every native matrix OS with Bun required.
The normal CI pytest job collects only root `tests/`, including the two small
golden-fixture and cross-runtime parity tests; runtime parity skips cleanly when
Bun is absent. Shared fixtures live in
`research/install-plane-spike/tests/spike_helpers.py`, without duplicated test bodies.
`scripts/test-ci.sh` resolves only
pytest, assertpy and PyYAML at exact repository-lock versions and uses
`uv --no-project --isolated`, so a local `.venv` cannot supply undeclared test
dependencies. Set `SPIKE_PYTHON` to the settings pin when invoking it. Build also
enforces Bun tests and typecheck. Collector runs exercise compiled TypeScript and
bundled Python separately. Shared uv 0.11.26 supports the selected CPython 3.14.6
on every target; local historical 3.14.7 results are not interchangeable with it.

Registry measurement publishes a scripts-free npm wrapper with optional os/cpu
packages to Verdaccio without uplinks. It installs with **both Bun and npm** using
fresh isolated configs/caches and `--ignore-scripts`, compares transported payload
hashes/modes, then runs the installed payload. Offline workers pack the same shape
with local-file optional dependencies and exercise actual client installations
under the measured restriction, using `--offline` and `--ignore-scripts`. npm is
an intentional measured client, not this repo's package-management tool.

Build records the setup temp/cache identity used to prime Verdaccio. Only the
server reuses it with `--no-install`; measured clients retain isolated fresh
config, temp and caches. Registry readiness has a bounded retry window, and both
shutdown waits retain errors without losing other evidence.
POSIX verifies owned-group absence. Windows launches suspended roots, assigns a
non-breakaway, kill-on-close Job Object, then resumes the retained primary thread.
Ownership survives root exit. Timeout/server cleanup terminates the job, queries
active membership and reaps within bounded waits; only observed empty membership
and successful reap/handle cleanup pass. Setup/assignment failures execute no
target code. Native CI includes an exited-parent/pipe-holding-child smoke; live
R5 Windows registry evidence observes empty job membership, parent reap and closed
handles. Cleanup errors preserve completed client measurements and sanitized
server logs, downgrade overall status and remain in durable registry evidence.

Before native isolation, both clients install the **same local tarballs** with
identical flags and fresh caches as a package-manager control. Per-client control
and restricted outcomes remain visible even when Bun selects incompatible local
optional packages. Linux namespace setup drops sudo privileges to the original
UID/GID and restores only explicitly passed setup environment; workers record
effective identity and refuse root package managers. Cleanup errors remain fatal,
and finally exports persisted JSON to logs/summary even on cleanup failure.

Linux requires passwordless noninteractive `sudo`, iproute2 `ip` with network
namespace/policy-rule support, util-linux `setpriv`, and `env`. Setup creates one
owned `install-plane-<uuid>` namespace, brings up only loopback, and adds
`ip route add 1.1.1.1/32 dev lo` using the canonical probe address. Inside that
namespace, `ip -4 rule add priority 1 prohibit` and its `-6` counterpart establish
an explicit kernel permission policy. Both the probe and the existing direct/npm
worker enter the **same namespace**, after groups and all capability sets are
dropped with `setpriv` and `no-new-privs` is set. No host routes/firewall or runner
control-plane processes are changed. Setup/route/rule errors, unavailable tools,
failed sudo, an inconclusive baseline or restricted probe, and unverified removal
cannot pass. Raw setup, route/rule readbacks, worker commands and namespace deletion
plus absence checks are retained. This is separate from dedicated Harden Runner.

A local disposable-namespace experiment observed connected unrestricted IPv4,
then `connect` EACCES/errno 13 under this policy. A worker-boundary child had
UID/GID 1000, no groups, zero capability sets, and could not remove the rule;
namespace removal was verified. The final PR 41332673633 and dispatch 41332723822 also
observe actual connect
EACCES/13 on both Linux architectures, both variants, with nonroot workers,
`groups=[]`, the shared restricted prefix and verified namespace deletion.
Earlier nft OUTPUT DROP/admin-prohibited timeouts and route-loss errno 101 remain
historical inconclusive observations; they are not used as proof. Socket
creation/configuration/cleanup failures are inconclusive, with
raw failure stages retained; only `connect` permission errors can prove denial.

Each independent scenario is persisted before the next starts. Account readiness,
status, parsing and token failures retain sanitized registry/server evidence;
random test credentials never enter runtime environments or evidence. Raw output
uses UTF-8 with replacement for undecodable tool output. No authored JS is added.

The dedicated Linux job starts Harden Runner first with an empty allowlist and
runs probes/installers directly under it. No same-host unrestricted baseline is
available there, so denial remains unverified. First-step blocking may prevent
checkout/download; setup failure then prevents measurement. The job never broadens
the measured allowlist. If measurement runs, raw JSON is printed to log and summary
before a best-effort artifact upload, which can itself be blocked. Native namespace
evidence cannot be credited to Harden Runner. See the report's explicit limits.

The [binding offline policy](https://github.com/lgtm-hq/ai-skills/issues/562#issuecomment-6557886641)
makes the standalone compiled binary primary transport with no install step;
npm-only local-file wrapper install is the documented fallback. Both variants
each run directly before their wrapper packing/install step, in a fresh HOME
under the same restriction. Direct execution plus npm decides offline status;
Bun local-file results are retained as evidence, not a gate. See the existing upstream
[oven-sh/bun#47640](https://github.com/oven-sh/bun/issues/47640). Both clients
remain required for registry/private-registry installs.

JSON distinguishes pass, fail, unverified and narrow quarantine observations.
Schema 3 separates `probe_denial_proven` from `installer_denial_proven`. Hosted
collection requires a clean checkout and matching `SPIKE_SOURCE_SHA`, records
`GITHUB_RUN_ATTEMPT`, and rejects invalid identity before scenarios. Local runs
have explicit `local observation` scope. Downloaded offline archive hashes are
not bound to expected source/build metadata; payload source identity remains
explicitly unverified. These checks do not authenticate build artifacts.
Windows direct CreateProcess does not test MotW shell/SmartScreen enforcement;
macOS CLI execution does not establish Finder behavior. Defender engine failures,
disabled Gatekeeper, third-party EDR, deliberate deep paths, unsigned fleet policy,
non-AVX2 baseline, musl and older Linux compatibility remain unverified.
The [final report](../../docs/research/install-plane-distribution.md) links green
[PR 41332673633](https://github.com/lgtm-hq/ai-skills/actions/runs/41332673633) and
[genuine dispatch 41332723822](https://github.com/lgtm-hq/ai-skills/actions/runs/41332723822),
exact clean source `fb4d21bbc68579606a283afa69af3eee664dab61`, all 24 raw JSON
identities/digests, current footprint and unsigned security commands/results.
Both variants pass registry (Bun and npm), no-Node, direct offline and npm fallback
on all five targets. Bun local-file selection still fails, evidence only under
[owner policy](https://github.com/lgtm-hq/ai-skills/issues/562#issuecomment-6557886641).

The report proves prototype/collector/build/pin bytes unchanged through `7909883`
and this documentation/main integration: only the test runner's pytest paths
change among the executed-source directories. Dispatch 41335569949 belongs to
`7909883` and must be collected separately; older JSON is not assigned to it.
Older R11/R12 and route-loss results remain historical, without altered raw files.

Apply the [merged Python-first escape hatch](https://github.com/lgtm-hq/ai-skills/blob/032ee309817813a9ef81bb2450cbed646a625222/docs/adr/0008-engine-runtime-build-and-install-planes.md):
B is equally deployable under required registry/no-Node/offline restrictions, so
one typed Python package owns build and install semantics. Install still cannot
resolve new sources, versions or edges; strict TypeScript only selects/invokes
the bundled payload. #566/#567/#578/#386 specifications must follow that boundary
before implementation. No production engine is implemented in this spike.

Dedicated Harden Runner's absent same-host baseline, independent payload-source
binding, Finder/SmartScreen and fleet enforcement, deliberate long paths and
read-only runtime limits remain U, not universal-green decision gates. The
[security policy](https://github.com/lgtm-hq/ai-skills/issues/562#issuecomment-6557818942)
is resolved: unsigned observations/documented signing needs suffice for #562;
free checksums, artifact/npm attestations, SLSA provenance and Sigstore/cosign
keyless signing remain production obligations. Developer ID/notarization is #619's
human-secret gate; Windows Authenticode is cost-gated #618. No paid or third-party
EDR experiment is required. Optional spike hardening stays in #614 under the
[owner review cap](https://github.com/lgtm-hq/ai-skills/issues/562#issuecomment-6561604904).
