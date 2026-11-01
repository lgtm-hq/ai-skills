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
This tiny regular-file UTF-8 profile is not the production v2 schema.

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
IPv4 control is required before explicit denial proves isolation; unavailable IPv6
is informational and timeouts remain unverified. Windows cleanup is verified.
No-Node control removes tool directories from PATH while preserving Windows loader
necessities and using disposable AppData/HOME locations.

## CI and raw evidence

The workflow runs on narrow PR paths and workflow dispatch, checks out the exact
PR head, and tests source parity with Bun required. Build also enforces Bun tests
and typecheck. Collector runs exercise compiled TypeScript and bundled Python
separately. Shared uv 0.11.26 supports the selected CPython 3.14.6 on every target;
local historical 3.14.7 results are not interchangeable with it.

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

JSON distinguishes pass, fail, unverified and narrow quarantine observations.
Windows direct CreateProcess does not test MotW shell/SmartScreen enforcement;
macOS CLI execution does not establish Finder behavior. Defender engine failures,
disabled Gatekeeper, third-party EDR, deliberate deep paths, unsigned fleet policy,
non-AVX2 baseline, musl and older Linux compatibility remain unverified.
A PR run does not complete the issue's green workflow_dispatch acceptance criterion;
ADR 0008 stays Proposed until the parent inspects live evidence and applies its rule.
