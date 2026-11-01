# Host load-path evidence spike (#563)

Recorded 2026-11-01 from `032ee309` on `research/563-host-load-paths`.
This is research only: no gateway, ADR, generated catalog or #562 files changed.
The future PR must merge after #562/PR #615, per epic #596.

| Host/interface  | Actually probed    | Environment                                           |
| --------------- | ------------------ | ----------------------------------------------------- |
| Claude Code CLI | 2.1.310            | linux-x86_64; clean config unauthenticated            |
| Codex CLI       | 0.164.0            | linux-x86_64; isolated auth.json copy                 |
| Cursor CLI      | 2026.10.22-27dcf5f | linux-x86_64; unauthenticated, no admin plugin policy |

The issue describes Codex 0.165.0 on another machine. This run verifies
**0.164.0**, not 0.165.0 or macOS. Cursor CLI does not certify Cursor IDE.

| State                | Cells |
| -------------------- | ----: |
| supported            |     6 |
| partial              |    10 |
| unverified           |    92 |
| platform-unavailable |     0 |
| policy-blocked       |     0 |
| source-unportable    |     0 |
| adapter-missing      |     0 |

The six supported cells are Codex instruction delivery in the two file modes
and Claude lifecycle delivery at native user/project, user-explode/user, and
repo-materialize/project. All 36 Cursor cells are unverified. The matrix also
includes 36 structurally undefined mode/scope combinations across the hosts;
they are not support candidates. A partial cell never authorizes widening
activation. [Record format](evidence-format.md), [command log](probe-log.md),
[probe kit](../../tests/fixtures/host-probe/README.md), and
[Cursor handoff](cursor-probe-checklist.md) give the reproducible details.

The owner [Cursor policy-host acceptance gate](https://github.com/lgtm-hq/ai-skills/issues/563#issuecomment-6557600027)
remains pending; all 36 Cursor cells stay unverified. Source fixes and offline
regressions do not satisfy that live acceptance or authorize wider activation.

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
- No evidence establishes Cursor's automatic project plugin drop path, nor
  either drop path under policy. `native-cursor.js` constructs the project
  path, but construction is not host loading evidence. #584 must retain its
  reject-unless-verified gate. No Copilot claim was tested by this issue.

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

### Cursor under plugin-import-disabled policy

| Question                                            | Answer                                                                                                                                                                                                    |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Do user/project plugins/local load?                 | Not determinable: requires maintainer-run policy machine; this laptop has no such policy.                                                                                                                 |
| Do rules, skills, agents and mcp.json load?         | Not determinable under policy. The CLI's clean-HOME invocation also lacked portable auth (R046).                                                                                                          |
| Cross-reads from .claude/skills and .agents/skills? | Not determinable here; the checklist tests each root separately and then duplicates. Do not promote ADR 0004's historical statement to this version's evidence.                                           |
| Detectable on-disk policy markers?                  | Not determinable without a policy machine. No marker key/path is invented; an empty policyMarkers list means no observation. Capture effective policy plus its source and test whether it is server-only. |

The [exact checklist](cursor-probe-checklist.md) is the outstanding human step.
All 36 Cursor cells remain unverified; the owner's
[policy-host gate](https://github.com/lgtm-hq/ai-skills/issues/563#issuecomment-6557600027)
remains pending. This work is **Part of #563**, not completion of that issue.
Neither authentication failure nor a missing policy test is `policy-blocked`.

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

| Issue | Claim or assumption                                                                         | Observed evidence / required correction                                                                                                                                                                                          |
| ----- | ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #384  | Version reference 0.165.0; config shape includes last_updated                               | Plugin contract already observed at 0.164.0; local marketplace table omitted last_updated. Version-bound the contract and make that field optional.                                                                              |
| #384  | Verification uses unfiltered plugin list --json                                             | R016 timed out; R029/R070 scoped to the local marketplace succeeded. Filter verification rather than depending on remote enumeration.                                                                                            |
| #384  | Native default whenever capability and policy allow; workflow record is an acceptance input | Native skill ignores disable-model-invocation (R031); workflow becomes a model-visible skill (R047/R057). Both are partial, so native capability alone cannot authorize user-only content. Preserve #583's strict semantic gate. |
| #583  | Problem locates disable-model-invocation loss in exploded delivery                          | Loss is also observed in Codex native delivery (R031). Apply the rejection/override rules to native envelopes as well. File-mode restriction preservation remains unverified.                                                    |
| #575  | Per-plugin envelopes list specialists as agents by role                                     | Codex accepts the experimental key but execution is unverified; command migration, rather than a native command directory contract, is what invoked. No evidence authorizes Codex agents/hooks generation as supported.          |
| #584  | Scope fix and remove/rollback use matching scope                                            | Scope behavior confirmed; Claude uninstall leaves cache (R083/R088/R093). Registration removal and cache cleanup need separate ownership-aware handling. Cursor project loading stays unverified.                                |
| #581  | Host-native repo files offer a route under restricted policy                                | Codex project skill/instruction route observed, but no Cursor policy route is established. The existing evidence gate must remain; do not count the policy scenario as proven.                                                   |
| #582  | Example local-plugin-import-disabled marker can drive detection                             | No disk marker was identified on this non-policy machine. Treat the example as a candidate pending the checklist, not a known setting or filename.                                                                               |
| #587  | Supported workflow cells count toward portability; native cells require tier: verified      | Codex native workflow is partial, not a portable user-only workflow. Cursor policy evidence is pending. Draft #563 has no tier field; #565/#585 must define it before #587 consumes it.                                          |

The last four caveats reinforce existing evidence gates; they are not claims
that the proposed implementations are impossible. No contradiction was found
with #384's user-only native scope or its cache-version safety recommendation.

## Cleanup and protected configuration

Before the probes, the original `config_snapshot.py` inventoried paths, nanosecond mtimes,
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

Recovered driver evidence D001–D003 in the [command log](probe-log.md) restores
the original source edit/cache comparison and MCP path replacements. Parent
reconciliation for #384/#583 should carry this narrower wording: snapshot
loading was observed for Codex 0.164.0/package 1.0.0, but cache-byte immutability
and same-version invalidation were not measured. The R031 invocation-restriction
loss remains evidenced; #583's strict semantic gate still applies.

Claude lifecycle invocation steps inspect the SessionStart hook log produced
by earlier authentication-failing requests. In the two file modes, R110/R112
inspect that log **after file removal**. No fresh session established
post-removal noninvocation. Final whole-root purge removed the owned hook logs
and other residue; it is the cleanup proof, not a new hook execution test.
