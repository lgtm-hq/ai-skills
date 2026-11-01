# Install-plane distribution spike (#562)

Throwaway code, separate from the gateway and future M6 engine. See the
[report](../../docs/research/install-plane-distribution.md) for evidence and limits.
Nothing here is in the gateway's npm publication allowlist.

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
uv run pytest tests/test_install_plane_spike.py tests/test_install_plane_collector.py
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
unavailable IPv6 is informational and timeouts remain unverified. Linux/macOS
probe and installers share a namespace/sandbox. R10 Windows program-specific rules
proved denial only for bundled Python; direct/npm execution succeeded but overall
offline stayed unverified. The new Windows-only controls compare the same fixed
IPv4 endpoint, argv, resolved executable path and SHA-256 before/during restriction
for direct A/B, actual npm Node and installed npm payloads. Seeded baseline copies
at future install paths are removed before real fresh installs. Windows npm uses
an explicit Node/npm-cli pair; mismatched launchers, missing/changed programs,
timeouts or failed cleanup cannot pass. A's `--spike-network-control` diagnostic
and emitted TypeScript Node module open only the fixed probe socket; normal
installation never calls them. Unit tests inject socket events and never connect.
These executable changes require fresh hosted evidence. Informational Bun is
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

The workflow runs on narrow PR paths and workflow dispatch, checks out the exact
PR head, and tests source parity with Bun required. `scripts/test-ci.sh` resolves only
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
The report preserves R3–R9 history separately and links inspected R10 PR
41315907240 and green dispatch 41316038552 at exact clean source
**80f328cb263c36c505ae1113224b7b36c36f85f6**. Their 24 schema-3 results establish
registry/no-Node passes on all five targets and direct-plus-npm offline passes on
four POSIX targets. Windows execution succeeds but denial remains unverified;
the new matched controls are not validated by R10. ADR 0008 stays Proposed for
this observable comparison gap; two unknowns cannot establish the Python-first
tie. Harden Runner's absent same-host baseline, independent payload provenance
and shell/fleet enforcement remain explicit limits, not universal-green gates.
The [security policy](https://github.com/lgtm-hq/ai-skills/issues/562#issuecomment-6557818942)
is resolved: unsigned observations and documented signing needs suffice for #562;
signed Mac work belongs to #619's human-secret gate, Authenticode is cost-gated
in #618, and no paid or third-party EDR is required.
