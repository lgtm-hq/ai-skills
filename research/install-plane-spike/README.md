# Install-plane distribution spike (#562)

Throwaway code, separate from the gateway and the future M6 engine. See the
[report](../../docs/research/install-plane-distribution.md) for evidence and limits.
No files here are in `npm/ai-skills/package.json`'s publish allowlist.

## Contract

Both CLIs take `FIXTURE EXCLUDE`, require a disposable `HOME`, and write only
`HOME/.spike-target`. The target must not already exist. They verify the archive
and every inventoried file, subtract the named capability, and reject retained
closures containing it. Unknown exclusions, unknown closure IDs, missing closure,
duplicate inventories, path traversal and malformed inventories fail before writes.
Output JSON represents UTF-8 file contents, with identical semantic output in both
runtimes. This tiny USTAR profile has regular files only, no compression, links,
directories, extended headers or binary file contents. It is not the v2 schema.

`fixtures/artifact.tar` is a 10 KiB **data fixture**, generated along with its JSON
by `scripts/fixture.py`. No compiled executables or runtime bundles are committed.
Change the generator, then run it; `--check` is the byte-drift gate.

## Local use

Use the repository's existing Python environment. A local build copies an already
installed uv-managed standalone Python; it does not download other OS runtimes.
Network is permitted while installing TypeScript tooling and priming Verdaccio.
All measured runtime invocations use an empty PATH and a credential-free environment.

```bash
unset PYTHONPATH
export UV_NO_SYNC=1
bun install --cwd research/install-plane-spike/ts --frozen-lockfile
uv run python research/install-plane-spike/scripts/fixture.py --check
uv run pytest tests/test_install_plane_spike.py
spike_output="${TMPDIR:-/tmp}/install-plane-562-build"
# Choose a new, absent output directory; build refuses to overwrite one.
uv run python research/install-plane-spike/scripts/build.py \
  --installed-python --output "$spike_output"
uv run python research/install-plane-spike/scripts/measure.py \
  --build "$spike_output" --results "$spike_output/results"
```

Run the collector on disposable machines: it attempts a Linux network namespace,
macOS sandbox, or temporary Windows outbound firewall rule and restores the rule
in `finally`. It records tool/permission failures. It never infers a pass from a
timeout, missing tool, zero exit alone, or optional dependency silently omitted.

## CI and raw evidence

`install-plane-spike.yml` builds natively on all five target pairs in `settings.json`.
Each native job tests both implementations and cross-runtime parity, builds the two
payloads, then collects the same scenarios. Setup/build downloads are separate from
offline workers. A second Linux job downloads both archives **before** activating
Harden Runner block mode with an empty allowlist, then installs local archives.
macOS and Windows Harden Runner use audit mode; their OS denial probes must pass
independently. No third-party EDR assertion is possible on these runners.

Artifacts contain `build.json` and `results/<os>-<arch>-<variant>.json`, plus separate
Linux `*-offline.json` records. Each external command record includes the exact argv,
cwd, full stdout/stderr, real exit (null for launch/timeout failure), and elapsed time.
The offline JSON preserves both inner install commands and outer isolation commands.
Verdaccio's full server output is retained. Runtime HOME is temporary; no credentials
are placed in runtime environments. Registry publication uses a disposable loopback
account, never repository or user credentials.

The stand-in has no uplinks and an explicit `registry_max_body_size` from settings.
Private packages have no scripts or launchers: the wrapper has exact-version
`optionalDependencies`; platform packages have `os`/`cpu` filters and contain the
payload. Other platforms are empty stand-ins in each native job. Bun publishes and
installs with `--ignore-scripts` using a fresh client cache, then the collector calls
the installed executable/bundle directly. This measures packaging and selection,
not a production npm launcher or an npm CLI client.

The JSON records distinguish `pass`, `fail`, `unverified` and quarantine `measured`.
A green collection workflow does not mean all scenario statuses passed. Build and
golden-test failures fail CI; restriction failures remain visible research evidence.
The report lists the unfulfilled issue criteria and the dispatch bootstrap path.
