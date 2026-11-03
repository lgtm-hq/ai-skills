# Renovate production regression sources

These byte-exact source snapshots come from Renovate 44.206.2, commit
`03949855f66eea416afa726ec3ab23223cccf294`. `sources.json` records their upstream
paths and SHA-256 digests. The accompanying `license.txt` is upstream's license.
Keep the `.ts.txt` files unchanged; the runner verifies their digests before
bundling them with Bun. Update the revision, source bytes, digests and locked
production dependency versions together when refreshing this fixture.

`../renovate-runner.ts` executes the actual YAML parser, JSONata extractor,
dependency construction, auto-replacement and re-extraction confirmation.
Production YAML options include `strict: false`. Parser/query/updater logic
is never reimplemented in the Python assertions. CST ranges only support
assertions about unchanged source spans.

The runner supplies narrow adapters for logging, filesystem writes, template
compilation, datasource migration, manager dispatch and unused formats. It uses
real Handlebars for the configured templates. Filesystem writes are inert because
the updater also returns the candidate source. No network or manifest vendor
code runs. The legacy regex snapshots allow RED controls against the previous
configuration; their adapter uses the common RE2/JavaScript RegExp subset and
fixed POSIX package-file paths. The production JSONata configuration does not
depend on those legacy adapters.

Tests live in `scripts/ci/npm/manifest_renovate_tests.py` and run mandatorily in
the prepared gateway gate after its frozen dependency install. Missing Bun or
locked dependencies cause errors, never skips or test-time installation.
The gate first runs `bunx --no-install tsc --noEmit -p tsconfig.fixtures.json`
from `npm/ai-skills`. This includes both maintained `.ts` fixtures and inherits
the gateway's `strict` and `noUncheckedIndexedAccess` settings. Bun's prepared
types describe the runtime and bundler API. The runner describes only the
consumed exports of the byte-verified bundle and locked YAML parser; JSON input,
snapshot metadata and optional CST nodes are checked at their unknown boundaries.
Shim source strings and the in-memory bundle remain runtime-generated; upstream
`.ts.txt` snapshots remain immutable. No maintained JavaScript fixture is allowed.
