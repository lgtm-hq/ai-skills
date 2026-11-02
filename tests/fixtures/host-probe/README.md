# Isolated host probe kit

Research fixture for #563; never install this package into a real home or
project. The three plugin envelopes and marketplaces are hand-written test
inputs, not production generated adapters. Tokens live only in payloads:

| Role | Payload | Sentinel |
| --- | --- | --- |
| skill | `probe-sentinel/skills/probe-skill/SKILL.md` | `PROBE-7f3a-skill` |
| instruction | `AGENTS.md`, `CLAUDE.md`, `rules/probe.mdc` | `PROBE-7f3a-instruction` |
| specialist | `agents/probe-specialist.md` | `PROBE-7f3a-specialist` |
| workflow | `commands/probe-workflow.md` | `PROBE-7f3a-workflow` |
| lifecycle | `hooks/hooks.json`, `hooks/sentinel.py` | `PROBE-7f3a-lifecycle` |
| integration | `.mcp.json`, `mcp/sentinel.py` | `PROBE-7f3a-integration` |

The initial published kit added lint-only Markdown headings and Python package
markers after measurement. PR #617 R1 then revised the MCP executable and its
schema to validate JSON-RPC requests, the advertised `probe_integration` name,
and empty-object arguments (omitted arguments default to `{}`). Invalid calls
return errors without the token; notifications are silent. Only a valid call
emits the integration token. R2 additionally handles `ping` with an empty result
and the original request ID, without emitting a token, and rejects null request
IDs. These are **post-measurement behavioral revisions**;
neither byte nor behavior equivalence to the measured MCP fixture is claimed.
Offline subprocess tests do not upgrade the original host discovery records.

The hook appends only to the explicitly supplied `$TMPDIR/probe-hook.log`.
The stdio MCP server uses Python's standard library, lists one read-only tool,
and returns the integration token. No network or dependency installation is
needed for either fixture. Run them only from a copied disposable tree.

## Personal Cursor source kit

[`cursor-macos-probe.sh`](cursor-macos-probe.sh) preserves the exact supplied
personal-Mac script as an archival fixture; do not use it for new runs.
Its SHA-256 is `6565f402a8554f5153479dfa5b32ca32345b4a16edba9886853e46374f8ffe8f`. Its
narrow lint exception is documented in [CONTRIBUTING.md](../../../CONTRIBUTING.md).
[`cursor-macos-probe-driver.sh`](cursor-macos-probe-driver.sh) is the maintained
macOS Bash 3.2 kit, preserving R6's controls and adding the canonical physical
path, isolated keychain with exact search-list restoration, and **This Mac**
local-agent prompt. It uses a fresh
HOME/project, TMPDIR/XDG roots, user-data and extensions directories, phased
six-role checks, restart/removal observations, private config fingerprints
(paths and SHA-256 only), sanitized JSON and an EXIT cleanup trap. The embedded
tagged hook writes to the isolated `tmp/probe-hook.log`; the embedded MCP oracle
emits its sentinel only for a valid call to the advertised tool. Offline tests
extract and execute these actual embedded programs with synthetic inputs and
run the full driver using fake OS/IDE commands in a disposable HOME.

Follow the [personal-Mac checklist](../../../docs/parity/cursor-probe-checklist.md)
and [owner
decision](https://github.com/lgtm-hq/ai-skills/issues/563#issuecomment-6558530548).
No employer-managed machine or organization policy data is used. Native-plugin
policy cells are owner-attested definitions; file-policy cells derive from the
matching personal results. The public setting is **Allow Local Plugin Imports**
([Cursor docs](https://cursor.com/docs/plugins#test-plugins-locally)).

The script's fingerprint excludes runtime-like paths and files at least 5 MiB;
it is not the `config_snapshot.py` inventory and does not certify whole-home
immutability. Changes have no assigned cause. The EXIT handler saves available
answers/logs as sanitized partial JSON before purging private scratch on
collection errors or handled interruptions. Incomplete comparisons have an
explicit reason and null change count; errors still exit nonzero. Hook removal
records a boundary before each restart and checks the exact removed tag after
a fresh prompt. The JSON cleanup status describes owned scratch only, not host
caches; `--keep` retains private scratch state. Review JSON before sharing.
The maintainer's personal Cursor IDE 3.27.22 run is recorded in the
[WRITE-ONCE raw
snapshot](../../../docs/parity/evidence/cursor/raw/2026-11-01-ide-darwin-arm64/cursor-probe-results-20261101T150149Z.json).
It was resumed manually in the same record format; its removal observations
are not the maintained driver's automatic hook-boundary evidence. The raw
snapshot and digest index must never be rewritten. The parent's publication,
review and required merge order after #562 still apply. Offline tests do not
upgrade the historical Codex/Claude evidence or certify a new IDE run.

## Prepare an isolated case

Run from the checkout before overriding the home for any child process:

```bash
probe_fixture="$PWD/tests/fixtures/host-probe"
probe_real_home="$HOME"
probe_parent="$(mktemp -d "${TMPDIR:-/tmp}/host-probe.XXXXXX")"
python3 "$probe_fixture/config_snapshot.py" "$probe_parent/before.json" || exit 1
probe_case="$probe_parent/case"
mkdir -p "$probe_case"/{home,claude,codex,tmp,project,config,cache,data,state}
cp -R "$probe_fixture" "$probe_case/marketplace"
git init -q "$probe_case/project"
cd "$probe_case/project"
```

Every host command below must have this environment prefix. Use a new case
root for each host/mode/scope and never resume an earlier host session:

```bash
env -i PATH="$PATH" LANG=C.UTF-8 \
  HOME="$probe_case/home" CODEX_HOME="$probe_case/codex" \
  CLAUDE_CONFIG_DIR="$probe_case/claude" TMPDIR="$probe_case/tmp" \
  XDG_CONFIG_HOME="$probe_case/config" XDG_CACHE_HOME="$probe_case/cache" \
  XDG_DATA_HOME="$probe_case/data" XDG_STATE_HOME="$probe_case/state" \
  DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
  codex --version
```

Replace only the final executable/argv. The actual run retained the installed
PATH, language, terminal, shell and configured certificate/proxy environment
names, with all credential environment variables dropped. The empty-env
recipe above is sufficient on machines without required proxy configuration.
Do not put proxy credentials into evidence. Redact paths to `~/probe/...`.

If invoking Codex requires auth, copy only its auth file, without displaying it:

```bash
install -m 600 "$probe_real_home/.codex/auth.json" "$probe_case/codex/auth.json"
```

Claude and Cursor had no portable auth-only file identified for this run.
Do not copy their settings, helpers, sessions, plugin trees or full homes.
If auth cannot be safely isolated, record the invocation unverified. Never
run a real helper from the owner's settings just to make a probe authenticate.

## Native commands

With the environment prefix on **every** command, use:

```bash
codex plugin marketplace add "$probe_case/marketplace" --json
codex plugin add probe-sentinel@probe-marketplace --json
codex plugin list --marketplace probe-marketplace --json
codex exec --ephemeral -s read-only \
  'Use the installed probe-skill skill and return only its sentinel.'
codex exec --ephemeral -s read-only \
  'Use the installed probe-sentinel workflow probe-workflow and return only its sentinel.'
codex mcp list --json
codex plugin remove probe-sentinel@probe-marketplace --json
codex plugin list --marketplace probe-marketplace --json
codex plugin marketplace remove probe-marketplace --json
```

Claude user, project and supplementary local scopes use separate cases:

```bash
claude plugin marketplace add "$probe_case/marketplace"
claude plugin install probe-sentinel@probe-marketplace --scope project
claude plugin list --json
claude -p --model haiku --max-turns 1 '/probe-sentinel:probe-skill'
claude mcp list
claude plugin uninstall probe-sentinel@probe-marketplace --scope project
claude plugin list --json
claude plugin marketplace remove probe-marketplace
```

The run also separately tested `marketplace add/remove --scope project`.
For a new full project-native cycle, give marketplace add and remove the same
project scope as install and uninstall. Inspect all settings and cache locations
before and after; Claude unregisters without deleting its cache.

Do not put the sentinel token into the prompt: it would prove nothing. Explicit
specialist and workflow invocations must actually load their role payloads;
listing a plugin is insufficient. Authentication failure can still trigger
SessionStart, so inspect the independent hook log without crediting the skill.

## File placement recipes

These describe the Python copy/write operations performed by the temporary
driver; the log preserves actual host commands, not an executable automation
framework. All destinations are under the isolated case.

| Host/role | user-explode/user | repo-materialize/project |
| --- | --- | --- |
| Codex skill | `$CODEX_HOME/skills/probe-skill/` | `project/.codex/skills/probe-skill/` |
| Codex instruction | `$CODEX_HOME/AGENTS.md` | `project/AGENTS.md` |
| Claude skill | `$CLAUDE_CONFIG_DIR/skills/probe-skill/` | `project/.claude/skills/probe-skill/` |
| Claude instruction | `$CLAUDE_CONFIG_DIR/CLAUDE.md` | `project/CLAUDE.md` |
| Claude specialist | `$CLAUDE_CONFIG_DIR/agents/probe-specialist.md` | `project/.claude/agents/probe-specialist.md` |
| Claude workflow | `$CLAUDE_CONFIG_DIR/commands/probe-workflow.md` | `project/.claude/commands/probe-workflow.md` |
| Claude hook | `$CLAUDE_CONFIG_DIR/hooks/` plus `settings.json` | `project/.claude/hooks/` plus `settings.json` |

Copy the respective payload file or directory from `probe-sentinel`. For the
Claude hook, copy `hooks/` then write a `hooks.SessionStart` settings entry
equivalent to `hooks/hooks.json`, replacing the command with
`python3 "<isolated-hooks-directory>/sentinel.py"`. No plugin-root expansion is
assumed for an exploded file. The actual run used `shutil.copytree/copy2` and
`json.dumps` for these operations. Remove only these owned scratch files.

Test `~/.agents/skills/probe-skill/` in a separate Codex case, then combine it
with `$CODEX_HOME/skills` and the native plugin to test duplicate discovery.
In a native case, change only the copied source skill token after install;
compare installed cache bytes and invoke again to distinguish live versus
snapshot loading. Do not change the checked-in fixture.
The original run's actual edit and result are preserved as
[D001](../../../docs/parity/probe-log.md#d001-source-edit-and-cache-comparison-before-r031):
the replacement was `PROBE-7f3a-skill-mutated`, source/cache comparison was
false, and R031 read the cached original token. No pre/post cache hash was
recorded; do not turn this case into a claim of unchanged cache bytes.

For the original Claude file-mode registrations, the driver copied `mcp/`
after R059/R062, then replaced the checkout path in isolated
`claude/.claude.json` or `project/.mcp.json` with the copied server path before
R060/R063. Exact recovered driver operations and subsequent health results
are
[D002/D003](../../../docs/parity/probe-log.md#d002d003-copied-mcp-path-replacement-after-r059r062).
These edits are driver steps, separate from the 112 process attempts. For a
future run, register the isolated copy directly as shown below.

The additional Codex envelope experiment copied the same marketplace to a
new case and amended only `.codex-plugin/plugin.json` with Python:

```python
payload.update(
    agents="./agents/",
    hooks="./hooks/hooks.json",
    mcpServers={
        "probe-integration": {
            "command": "python3",
            "args": [str(case / "marketplace/probe-sentinel/mcp/sentinel.py")],
        },
    },
)
```

Here `case` is the isolated case directory and `payload` is the loaded JSON
mapping. Then the host commands R042–R045/R058 installed, listed and started
the package. No specialist was invoked; no hook log was produced. Key
acceptance alone did not establish interpretation or role support.

Integration registration, still with the environment prefix:

```bash
codex mcp add probe-integration -- python3 "$probe_case/codex/mcp/sentinel.py"
codex mcp list --json
codex mcp remove probe-integration
claude mcp add --transport stdio --scope user probe-integration -- \
  python3 "$probe_case/claude/mcp/sentinel.py"
claude mcp list
claude mcp remove probe-integration --scope user
```

Copy `mcp/sentinel.py` to the target first. Use Claude `--scope project` for
the project case; it writes `.mcp.json` and may require explicit MCP approval.
Listed-only integration evidence stays partial/discovered here.

For offline Codex discovery, start `codex app-server`, send initialize and
**wait for id 1**, then initialized and skills/list; keep stdin open until id 2:

```json
{"id":1,"method":"initialize","params":{"clientInfo":{"name":"probe","version":"1.0.0"}}}
{"method":"initialized"}
{"id":2,"method":"skills/list","params":{"cwds":["~/probe/project"],"forceReload":true}}
```

Expand that cwd alias to the isolated absolute project path before sending.
R047–R049 show successful responses. Early EOF attempts are recorded failures
of the probe protocol and do not establish absence.

## Cleanup and protected configuration

First perform scope-matched host remove/list checks. Inspect plugin config
tables, settings enablement, and cached payloads independently. Delete the
copied file-mode destinations, not any real host paths. The research driver
then deleted every case directory it had created with `shutil.rmtree`, using
the list of owned immediate children of its temporary parent. This removed
auth copies, cached trees, marketplaces, projects, hook logs and runtime state.
It verified that zero case directories remained.

Before changing the parent shell's home, compare protected inventories:

```bash
python3 "$probe_fixture/config_snapshot.py" "$probe_parent/after.json" && \
  cmp "$probe_parent/before.json" "$probe_parent/after.json"
```

Use fresh before/after destinations and check collector exits. The collector
does not support symbolic links in the protected scope, including skill/plugin
directories, host roots, payload ancestors, linked files, dangling links or
cycles. HOME and its ancestors must also be physical directories; use the
canonical physical HOME path if the platform provides an alias. Links under
explicitly excluded runtime roots are outside the check. Unsupported nodes,
unreadable directories/files and metadata errors abort collection, without a
success summary or a new inventory artifact. Do not skip the error, compare a
stale artifact or call the inventory unchanged. Stop the probe if the baseline
fails; if final collection fails, report incomplete verification while still
purging owned scratch state. Never change real-home links to make collection
pass. Coverage is limited to selected suffixes/auth names: kit JSON/TOML/YAML
configuration, Markdown/MDC payloads and Python/shell hook/MCP executables.
Collection remains inside the named host roots; it is not whole-home traversal
and is not atomic against concurrent changes. Offline disposable-HOME
regressions prove selected-format coverage and link/error rejection only,
not live coverage or absence of residue.

If they differ, compare paths/mtimes/digests locally, never print contents,
never restore over concurrent work, and report the limitation. This run found
nine changing Codex runtime-cache entries in the final comparison; the other
5,372 of 5,381 entries matched **under the old collector only**. Seven changes
affected only mtime; two also changed hash. That collector excluded runtime-like
names anywhere in a path, including legitimate skill/plugin payloads named
`plans`, `logs`, `sessions`, etc. Its narrower coverage does not prove the whole
protected inventory unchanged. R2 excludes only known runtime roots for each
host and preserves same-name nested payloads. The correction was tested only
with disposable HOME fixtures; no real-home remeasurement or certification of
corrected coverage took place.
See [the findings](../../../docs/parity/README.md) for the exact inventory
scope and aggregate digests. Finally delete the owned temporary parent,
including private inventories, after saving only sanitized evidence. Do not
run unprefixed host commands against real config to prove cleanup.

## Maintained guard limits

The archival supplied script remains digest-pinned and unchanged; all hardening
applies to the maintained driver. Interactive `y` invocation answers mean that
the maintainer reports the requested token returned; curated token strings are
interpretations of those answers, not verbatim model transcripts. Hook/MCP logs
are separate invocation traces. D004 in the command log recovers the original
Claude file-mode hook reads before removal. Post-removal hook noninvocation,
whole-host cache cleanup and same-version update behavior remain unverified.

Process matching uses the portable POSIX ERE subset and intentionally includes
helpers below the selected app's `Contents/` tree only when their flattened argv
contains the exact isolated user-data directory. Explicit app aliases are
canonicalized. Startup isolation is checked after the isolated app opens; this
is not a prelaunch filesystem sandbox. BSD/macOS matching still needs native
confirmation; Linux tests use synthetic process tables and never signal an IDE.
A failed keychain creation may leave scratch retained with cleanup unverified
when the system cannot confirm deletion/restoration; do not infer a leak or a
successful purge from an incomplete control.

The config collector excludes only direct known runtime roots, including Cursor
extensions. Nested payload directories named `node_modules` remain protected;
unsupported links fail closed rather than silently omitting payloads. Concurrent
file mutation during reads and permission failures abort collection. Comparison
is not atomic across files. Inventories, auth-file digests and aggregate inventory
digests stay private; publish counts and limitations, then promptly delete the
private inventories after retaining sanitized evidence. Never publish hashes
derived from credential files. The maintained shell fingerprint is narrower,
excludes only exact runtime-root names, and does not cover newline filenames.

The first committed hook blob at `ffa0f08` and the current hook blob are both
`e24936fa4bc46d35acf253e56ad5bf91ca2782e2` (an empty Git diff). Its formatting
already uses `Path(...).open(mode="a", encoding="utf-8")` and appends the same
sentinel line to the explicit TMPDIR. The earlier preformat bytes were not
retained as a separate artifact; the historical lint-only description is not
an exact-byte comparison to those missing bytes or a native remeasurement.
