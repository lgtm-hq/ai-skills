# Host load-path evidence spike (#563)

Original Linux probes recorded 2026-11-01 from `032ee309`; personal-Mac Cursor
evidence recorded 2026-11-01, building on R6 `e5e4969` on
`research/563-host-load-paths`.
This is research only: no gateway, ADR, generated catalog or #562 files changed.
The source work landed as #563/PR #617; the later runtime decision is recorded
in [Accepted ADR 0008](../adr/0008-engine-runtime-build-and-install-planes.md).

| Host/interface  | Actually probed    | Environment                                           |
| --------------- | ------------------ | ----------------------------------------------------- |
| Claude Code CLI | 2.1.310            | linux-x86_64; clean config unauthenticated            |
| Codex CLI       | 0.164.0            | linux-x86_64; isolated auth.json copy                 |
| Cursor CLI      | 2026.10.22-27dcf5f | linux-x86_64; unauthenticated, no admin plugin policy |
| Cursor IDE      | 3.27.22            | darwin-arm64, macOS 27.2; isolated personal install   |

The issue describes Codex 0.165.0 on another machine. This run verifies
**0.164.0**, not 0.165.0 or macOS. Cursor CLI does not certify Cursor IDE.

| State                | All cells | Cursor CLI | Cursor IDE, no policy | Cursor IDE, policy |
| -------------------- | --------: | ---------: | --------------------: | -----------------: |
| supported            |        34 |          0 |                    17 |                 11 |
| partial              |        12 |          0 |                     1 |                  1 |
| unverified           |       116 |         36 |                    12 |                 12 |
| platform-unavailable |         0 |          0 |                     0 |                  0 |
| policy-blocked       |        12 |          0 |                     0 |                 12 |
| source-unportable    |         0 |          0 |                     0 |                  0 |
| adapter-missing      |         6 |          0 |                     6 |                  0 |

Counts cover all 180 YAML cells: 108 original CLI cells, 36 personal Cursor IDE
cells and 36 owner-defined/derived Cursor IDE policy cells. Cursor totals across
interfaces/policies: 28 supported, two partial, 60 unverified, twelve
policy-blocked and six adapter-missing. The 36 Cursor CLI cells retain their
original unverified results; CLI authentication failure establishes no IDE
behavior. The twelve undefined pairs in each IDE dimension remain unverified
under #581. The original CLI matrix has 36 undefined pairs across all hosts.

All six roles invoked from user-native, user-explode/user and
repo-materialize/project in the personal IDE. The user-explode skill is partial
because its invocation restriction is unconfirmed. File-policy cells inherit
these outcomes; all native-plugin policy cells remain owner-attested blocked.
The six previously supported Codex/Claude cells and their findings are unchanged.
A partial cell never authorizes widening activation.
[Record format](evidence-format.md), [command log](probe-log.md),
[probe kit](../../tests/fixtures/host-probe/README.md), and
[Cursor checklist](cursor-probe-checklist.md) provide the reproducible details.

The binding [owner
decision](https://github.com/lgtm-hq/ai-skills/issues/563#issuecomment-6558530548)
requires only personal Cursor on an isolated personal Mac. No employer-managed
machine is probed or organization policy names/values/sources collected.
[Cursor's public docs](https://cursor.com/docs/plugins#test-plugins-locally)
name **Allow Local Plugin Imports**. Native-plugin policy records cite these
sources as owner attestation and definition, with no empirical policy-host
measurement. File-policy records depend on the exact matching personal IDE
cell, now measured by `ue-<role>` or `rm-<role>` JSON checks for defined routes. The
[minimal IDE/policy extension](evidence-format.md#cursor-ide-and-policy-extension)
is ratified by [ADR 0009](../adr/0009-capabilities-and-parity.md); the production
schema remains #585 work.

The maintainer's returned
[raw
snapshot](evidence/cursor/raw/2026-11-01-ide-darwin-arm64/cursor-probe-results-20261101T150149Z.json)
is committed byte-for-byte, with 41 checks and hook/MCP logs. It is WRITE-ONCE:
new runs add files, never edit this one.
[INDEX.sha256](evidence/cursor/raw/INDEX.sha256)
and pytest enforce integrity. The personal-evidence requirement is satisfied;
publication, review and the required merge order after #562 remain with the parent.
No issue is edited or closed by this revision.

## Personal-Mac Cursor run notes

- Cursor IDE 3.27.22 ran on darwin-arm64, macOS 27.2, on 2026-11-01, with
  throwaway HOME, user-data/extensions directories and an isolated empty keychain.
  The local **This Mac** agent is required; a Cloud agent cannot see local files.
  The first skill attempt used Cloud by mistake; the local slash invocation passed.
- macOS needs a keychain under the throwaway HOME. Without it Cursor reports
  **Keychain Not Found**. Never click **Reset To Defaults**, which resets the real
  account keychain. Restore the account's original search list exactly; the
  maintained driver preserves paths containing spaces and an empty search list.
- Resolve `/var` to `/private/var` before opening the project. The alias produced
  an empty window or unrunnable project items; reopening the physical path fixed
  the project file-mode checks. Project-native plugins still failed after two
  restarts on the physical path.
- The driving shell was interrupted. The maintainer resumed the run by hand,
  recording the remaining checks in the same format. The raw file is the
  returned transcript, without invented automatic cleanup fields.
- The reported 29 real-config changes came from normal Cursor opened by mistake
  mid-run (built-in skills sync, chats and statsig cache) and a concurrent Claude
  Code session, per the maintainer. The maintainer found no probe-named or
  `PROBE-7f3a` residue in real `~/.cursor`, `~/.claude` or `~/.agents`.
  Phase `*-removed=y`, `xread-removed=y` and `final-clean=y` confirm removal after
  restarts. These observations do not establish whole-inventory immutability or
  an automatic hook-removal boundary; those fields are absent from the snapshot.

The exact supplied [script](../../tests/fixtures/host-probe/cursor-macos-probe.sh)
is archived unchanged. It predates R6 and has ShellCheck/shfmt findings, so the
narrow archival exception is documented in [CONTRIBUTING.md](../../CONTRIBUTING.md).
The [maintained driver](../../tests/fixtures/host-probe/cursor-macos-probe-driver.sh)
keeps R6's launcher isolation and failure handling, adds the Mac fixes and the
This Mac prompt, and remains linted and tested. Offline tests make no new IDE
claims. #620 adds a separate unattended `cursor-agent` probe.

## Findings for #584

- Claude install scope is real. `plugin install -s user|project|local` wrote
  enablement into the isolated config's `settings.json`, the disposable repo's
  `.claude/settings.json`, or `.claude/settings.local.json`, respectively
  (R019–R028). Shared install bookkeeping and cache stayed under the isolated
  Claude config. The gateway's `native-cli.js` passes no scope, so its comment
  that host CLIs do not take scope is false for Claude. Marketplace add also
  accepts `--scope project` and writes the project settings (R054).
- `uninstall --scope` removed the matching enablement and list entry
  (R080–R093), but Claude retained the cached tree. Final purge of the owned
  scratch roots removed that residue. Do not equate an empty plugin list with
  an empty cache, or delete a shared cache without ownership checks.
- Cursor IDE **3.27.22 on macOS 27.2/darwin-arm64** did not load
  `project/.cursor/plugins/local` after two restarts: no plugin, skill, rule,
  specialist, workflow, hook or MCP. Checks `npp-plugin-listed`, all six
  `npp-<role>`, `npp-integration-proc` and `npp-relaunch` were `n`. The six
  project-native cells are `adapter-missing/absent`, confirming #584's
  project-scope bug. All six roles invoked from `~/.cursor/plugins/local`
  (`np-<role>=y`, hook events and `np called`); removal passed. #584 should reject
  project-native plans before writes and point to the verified
  `repo-materialize/project` route. Directory existence is no capability proof.
  Native plugins under policy remain owner-defined blocked, not measured on a
  policy host. Codex/Claude findings are unchanged; no Copilot claim was tested.
- Cursor also reads skills from both `~/.claude/skills` and `~/.agents/skills`:
  `xread-claude=y`, `xread-agents=y`, and `xread-removed=y` prove invocation and
  removal. Duplicate discovery or repeated execution in one turn was not tested.

## Codex native contract for #384

- Local marketplace add, plugin add, scoped marketplace list, plugin remove,
  and marketplace remove all accepted `--json` in **0.164.0**. `plugin add
--scope project` failed with exit 2 (R041). Only user-native registration is
  evidenced. No project-only native route is established.
- `.agents/plugins/marketplace.json` accepted a name and a plugin entry with
  `{name, source: {source: "local", path: "./probe-sentinel"}, policy:
{installation: "AVAILABLE", authentication: "ON_INSTALL"}}`. The baseline
  plugin envelope contained `name`, `version`, `description`, `skills:
"./skills/"`, and `interface.displayName/shortDescription`. These are tested
  fixture fields, not a complete host schema.
- The fixture carried all three host envelopes together. This verifies that
  exact mixed-envelope package, including Codex's compatibility migration;
  it does not isolate which manifest supplied every default. A Codex-only
  envelope and independently varied optional fields need separate probes.
- Local add wrote `[marketplaces.probe-marketplace]` with `source_type =
"local"` and `source`; it did **not** write `last_updated`. Plugin add wrote
  `[plugins."probe-sentinel@probe-marketplace"] enabled = true`. The installed
  tree was copied into `$CODEX_HOME/plugins/cache/probe-marketplace/
probe-sentinel/1.0.0/`, rather than linked to the source.
- The recovered D001 driver step changed the isolated source token from
  `PROBE-7f3a-skill` to `PROBE-7f3a-skill-mutated`. Source and cache then differed
  (`CACHE_IS_SOURCE False CACHE_SYMLINK False`); R031 read the installed cached
  payload and returned the original token. This supports snapshot loading in
  this **0.164.0/package 1.0.0** case. No pre/post cache hashes were captured,
  so unchanged cache bytes are not proven. Same-version re-add/update
  invalidation was not tested; retain digest-version safety until verified.
- Native skills are namespaced: `probe-sentinel:probe-skill` (R047).
  `disable-model-invocation: true` did not stop the model selecting this skill
  when asked to choose any appropriate skill (R031). The native skill cell is
  **partial**, with `lostFields: [invocation]`.
- Codex migrated `commands/probe-workflow.md` into
  `.codex-plugin/migrated-command-skills/source-command-probe-workflow/SKILL.md`,
  listed as `probe-sentinel:source-command-probe-workflow`, and invoked its token
  (R047/R057). This is a model-visible skill conversion, not verified user-only
  workflow semantics. The workflow cell is **partial**.
- `plugin remove` removed the plugin table and cache. Marketplace remove then
  removed its table, leaving an empty isolated config (R067–R078). Empty results
  came from `plugin list --marketplace probe-marketplace --json`. The unfiltered
  list timed out after 30 seconds (R016); use the local marketplace filter for
  deterministic verification instead of assuming remote enumeration is cheap.

## Answers to the probe questions

### Codex

| Question                                    | Answer and evidence                                                                                                                                                                                                                                                                                                   |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Local marketplace pinned or live?           | D001 source edit produced different source/cache bytes; R031 read the cache and returned the original token. Snapshot loading observed for this case; unchanged cache bytes and same-version re-add remain unverified.                                                                                                |
| Namespaced skills?                          | Yes: `probe-sentinel:probe-skill`; migrated command gets its own namespaced skill name (R047).                                                                                                                                                                                                                        |
| Double loads across user roots and plugins? | Yes at discovery: R047 returned three separate probe-skill entries: native, `$CODEX_HOME/skills`, and `~/.agents/skills`. The two user entries have the same unqualified name. Each root invoked independently (R017/R033/R036). Multiple executions in a single turn were not tested.                                |
| Any project scope?                          | `.codex/skills` and repo `AGENTS.md` invoked (R038/R039), even in the untrusted disposable repo. Project config/hooks/exec policies were separately trust-gated. Native `--scope project` is rejected; trusted project-native registration is not determinable.                                                       |
| Does plugin.json accept agents/hooks/MCP?   | An envelope with `agents`, `hooks`, `mcpServers` installed (R043); explicit MCP appeared in `mcp list` (R045). Specialist invocation was not tested, and the lifecycle log remained absent after R058. Acceptance of a key does not prove it was interpreted. Agent/hook execution semantics remain not determinable. |
| Does remove delete config.toml table?       | Yes, the plugin table and cache disappeared; marketplace remove then deleted its table (R069/R072/R075/R078).                                                                                                                                                                                                         |
| Where do AGENTS.md and prompts load?        | User `$CODEX_HOME/AGENTS.md` and repository-root `AGENTS.md` invoked instruction token (R034/R039). Standalone user/project prompts and their interactive invocation were not tested; prompt paths are not determinable through this bounded exec probe. Native `commands/` migration is evidenced separately.        |

Baseline `.mcp.json` also appeared in Codex's MCP listing, but its argument still
contained literal `${CLAUDE_PLUGIN_ROOT}` (R055). Successful listing is not proof
of interpolation or connection. With an explicit isolated path in `mcpServers`,
listing worked. No MCP config table was created by native plugin import.
`features list` reported `plugins` and `hooks` stable, `plugin_hooks` removed
(R056); feature flags alone do not prove a lifecycle projection.

### Cursor personal results and owner-derived policy

| Question                                            | Answer and evidence                                                                                                                                                                                                                                                                                                                                            |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Do user/project plugins/local load?                 | No policy: user root supports all six roles (`np-<role>=y`, hook/MCP logs); project root loads none after two restarts (`npp-<role>=n`, `npp-plugin-listed=n`, `npp-relaunch=n`). Under policy: both are `policy-blocked` by owner attestation/definition and public docs; **Allow Local Plugin Imports** is off by default on Enterprise.                     |
| Do rules, skills, agents and mcp.json load?         | Yes, all six file-mode roles invoke from user `~/.cursor` (`ue-<role>`) and project `.cursor` (`rm-<role>`), including token-returning MCP calls. Project `AGENTS.md` also invokes (`rm-agentsmd=y`). Policy file modes follow these results by owner decision. Project MCP's initial enabled/default setting is not determinable because it was not recorded. |
| Cross-reads from .claude/skills and .agents/skills? | Yes: `xread-claude=y` and `xread-agents=y` returned each root's skill sentinel; `xread-removed=y` verified removal. The roots work independently in this combined phase; duplicate discovery or multiple executions in one turn are not determinable because they were not measured.                                                                           |
| Does disable-model-invocation hold?                 | Not determinable: explicit user-explode slash invocation works; `ue-skill-autoinvoke=y` returned the token without naming the skill, but skill invocation versus file search is unconfirmed. Record a suspected `lostFields: [invocation]` and partial user-explode skill. Other tested skill payloads used `false`; no restriction claim follows.             |
| Detectable on-disk policy markers?                  | Not determinable: no on-disk detector was tested or established, and no organization policy data was collected. `policyMarkers` names only the public **Allow Local Plugin Imports** setting, with decision/docs provenance in the separate IDE policy records.                                                                                                |

The [completed personal-Mac checklist](cursor-probe-checklist.md) links the
WRITE-ONCE raw snapshot. Every specified Cursor question is answered or bounded
above. Separate identities retain the CLI evidence; these IDE results do not
upgrade the unauthenticated CLI run.

### Claude Code

| Question                                                     | Answer                                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| What do project/local scopes write?                          | Project enablement: `.claude/settings.json`; local enablement: `.claude/settings.local.json`. Both have projectPath in user-config install bookkeeping and a shared user-config cache. Marketplace `--scope project` writes extraKnownMarketplaces into project settings (R054). Scope-matched removal clears registrations but retains cache. |
| Does CLAUDE_PLUGIN_ROOT resolve for local-marketplace hooks? | Yes: native user/project/local SessionStart appended `PROBE-7f3a-lifecycle` under each isolated TMPDIR. MCP health checks resolved it to the local marketplace source as well (R022/R051/R053).                                                                                                                                                |
| disable-model-invocation native versus exploded?             | Not determinable: all isolated model invocations failed authentication before skill execution. The native and file-mode fixtures carry the flag, but file presence is not semantic evidence. Hooks firing despite model auth failure do not establish skill behavior.                                                                          |

## Downstream spec reconciliation for the parent

Read-only issue inspection covered #584, #384, #583, #575, #581, #582, #587.
No issue was edited. These are precise corrections or limitations to carry
forward before implementation:

| Issue | Claim or assumption                                                                         | Observed evidence / required correction                                                                                                                                                                                                                                                      |
| ----- | ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #384  | Version reference 0.165.0; config shape includes last_updated                               | Plugin contract already observed at 0.164.0; local marketplace table omitted last_updated. Version-bound the contract and make that field optional.                                                                                                                                          |
| #384  | Verification uses unfiltered plugin list --json                                             | R016 timed out; R029/R070 scoped to the local marketplace succeeded. Filter verification rather than depending on remote enumeration.                                                                                                                                                        |
| #384  | Native default whenever capability and policy allow; workflow record is an acceptance input | Native skill ignores disable-model-invocation (R031); workflow becomes a model-visible skill (R047/R057). Both are partial, so native capability alone cannot authorize user-only content. Preserve #583's strict semantic gate.                                                             |
| #583  | Problem locates disable-model-invocation loss in exploded delivery                          | Loss is also observed in Codex native delivery (R031). Apply the rejection/override rules to native envelopes as well. File-mode restriction preservation remains unverified.                                                                                                                |
| #575  | Per-plugin envelopes list specialists as agents by role                                     | Codex accepts the experimental key but execution is unverified; command migration, rather than a native command directory contract, is what invoked. No evidence authorizes Codex agents/hooks generation as supported.                                                                      |
| #584  | Scope fix and remove/rollback use matching scope                                            | Scope behavior confirmed; Claude uninstall leaves cache (R083/R088/R093). Registration removal and cache cleanup need separate ownership-aware handling. Cursor 3.27.22 project-native loading fails after two restarts; reject that route before writes and offer repo-materialize/project. |
| #581  | Host-native repo files offer a route under restricted policy                                | Codex project skill/instruction route observed. Owner attests Cursor file-policy equivalence; personal IDE 3.27.22 file results now support all roles except the partial user-explode skill. Preserve that suspected invocation loss.                                                        |
| #582  | Example local-plugin-import-disabled marker can drive detection                             | Public Allow Local Plugin Imports names the policy; no on-disk detector was identified. The owner decision does not authorize organization policy collection or invent a setting filename.                                                                                                   |
| #587  | Supported workflow cells count toward portability; native cells require tier: verified      | Codex native workflow is partial, not a portable user-only workflow. Cursor file-policy cells now derive from the measured personal IDE cells; native policy remains owner-attested blocked. Draft #563 has no tier field; #565/#585 must define it before #587 consumes it.                 |

The last four caveats reinforce existing evidence gates; they are not claims
that the proposed implementations are impossible. No contradiction was found
with #384's user-only native scope or its cache-version safety recommendation.

## Cleanup and protected configuration

Before the probes, the original `config_snapshot.py` inventoried paths, nanosecond
mtimes,
and SHA-256 under the real `.claude`, `.codex`, `.cursor`, `.agents`, plus
`~/.claude.json` when present. It selected configuration suffixes and auth-file
names, but excluded any path containing a runtime-like directory name anywhere.
That also omitted legitimate skill/plugin payloads named `plans`, `logs`,
`sessions`, etc. The identical original algorithm ran after all probes; its
coverage was narrower than the intended protected inventory.

With that **old collector only**, there were **5,381 entries before and after**:
5,372 matched exactly in the final
post-validation comparison. The main
config/auth/instruction/settings files, all inventoried Claude/Cursor files,
and the absence of `.agents` were unchanged. Nine Codex runtime-cache entries
changed during the run: `models_cache.json`, three JSON files under
`cache/{codex_apps_server_info,codex_apps_tools,remote_plugin_catalog}`, and
`plugins/cache/openai-curated-remote/{pages,plugin-management,sites,
openai-templates,work-pets}/.codex-remote-plugin-install.json`. Other Codex
sessions were active; causation is not established. Seven entries changed only
mtime; `models_cache.json` and the remote plugin catalog changed both mtime and
hash. The immediate post-probe comparison had six changed entries; the final
comparison includes the three additional runtime cache paths. No attempt was made to
restore or overwrite these files. The counts, changes and aggregate digests
below describe only the old collector's selected entries, not omitted payloads
or the corrected collector's coverage. **Whole protected-inventory immutability
is not proven**, even apart from the nine changes.

PR #617 R2 restricts runtime exclusions to known roots for each host; nested
skill/plugin payloads with those names are now included. Only disposable-HOME
offline regressions exercised the correction. No real-home inventory was
remeasured, and the historical comparison does not certify corrected coverage.

The collector now also fails closed on links instead of silently omitting
linked skill/plugin directories. Links anywhere in the protected scope,
including host roots, payload ancestors, dangling links and cycles, are
unsupported; HOME and its ancestors must be physical directories too. Linked
files and non-regular payload nodes are rejected. Known excluded runtime roots
remain outside this check. Directory-listing, metadata and read errors abort
collection rather than skipping entries. A failed collection has no success
count/digest and cannot establish an unchanged comparison; check its exit code
before comparing artifacts. This is a suffix/name-selected inventory, not an
atomic snapshot or a complete inventory of every host file. These source changes
have only offline disposable-HOME coverage: no live inventory acceptance,
historical evidence upgrade or no-residue claim follows from them.

Private inventory aggregate digests:

```text
before 3b45982f5073409e576ac9082d7fa8c67e8b5c3f50f19412e0ab185232cc6943
after  71a03e0be156a4708b91317daf2fb362b9035651382fc839f49cafc66e8d145d
```

Host remove/list/config checks are preserved in R067–R112. Codex removed its
probe cache and config tables. Claude left cached files after unregistering.
All 17 isolated case directories were then deleted, including copied auth,
marketplaces, projects, hook logs, caches and host-created state; zero case
directories remained. Private inventories and the temporary driver are removed
after recording their summaries. No sentinel was installed in real host config.

The log contains 112 process attempts: 100 exit 0, seven exit 1 (six Claude
auth failures and one Cursor auth failure), one exit 2 (Codex project scope),
one timeout/124, and three app-server shutdown exit codes not captured after
successful skills/list responses. Model attempts: 10 Codex, six Claude, one Cursor.
R009 is `codex exec --help` and is excluded from model attempts. Five
early app-server attempts produced no usable response and are explicitly
excluded from discovery conclusions. None of the offline tests use network.

## Post-measurement revisions (PR #617 R1/R2)

The MCP fixture now validates the advertised tool name and empty-object
arguments and returns JSON-RPC errors for invalid requests. The integration
token is emitted only by a valid tool call, rather than also as server metadata.
R2 adds an empty-result `ping` response, preserves request IDs and notification
silence, and rejects explicit null request IDs. Pings never emit the sentinel.
This is an executable behavior/schema revision after the measurement, not a
byte- or behavior-equivalent copy of the measured fixture. Offline subprocess
tests exercise the revised oracle; they do not certify host wiring. Existing
listed-only MCP records remain **partial/discovered**, with no retroactive
model/tool invocation claim.

Recovered driver evidence D001–D004 in the [command log](probe-log.md) restores
the original source edit/cache comparison, MCP path replacements and
pre-removal file-mode hook reads. Parent
reconciliation for #384/#583 should carry this narrower wording: snapshot
loading was observed for Codex 0.164.0/package 1.0.0, but cache-byte immutability
and same-version invalidation were not measured. The R031 invocation-restriction
loss remains evidenced; #583's strict semantic gate still applies.

Claude lifecycle invocation steps inspect the SessionStart hook log produced
by earlier authentication-failing requests. [D004](probe-log.md#d004-pre-removal-claude-file-mode-hook-reads-after-r060r063)
recovers the original pre-removal reads immediately after R060/R063. In the two
file modes, R110/R112 inspect that log **after file removal**. No fresh session established
post-removal noninvocation. Final whole-root purge removed the owned hook logs
and other residue; it is the cleanup proof, not a new hook execution test.
