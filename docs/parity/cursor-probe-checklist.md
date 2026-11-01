# Cursor policy-machine probe checklist

Human handoff for #563. **Not executed:** the laptop has no admin policy
disabling plugin import, and the isolated CLI has no portable authentication.
Every Cursor cell remains `unverified`, reason: requires maintainer-run policy
machine. Do not infer policy behavior from CLI help or directory presence.

## Isolation and effective policy

1. On the work machine, record Cursor IDE and CLI versions separately, OS,
   architecture, date and active team. Remove account/team identifiers from
   committed evidence. Verify in the host's effective admin policy view that
   plugin import is disabled. Capture the setting's exact name, value and
   source, without guessing a disk key from this document.
2. Follow the [kit isolation recipe](../../tests/fixtures/host-probe/README.md).
   Snapshot real config **before** testing. Use a fresh temporary HOME, all XDG
   directories, and a temporary git project. The home override must apply to
   every Cursor child. Copy only a known auth-only file if necessary. Never
   copy a full `cli-config.json` containing unrelated user preferences/helpers.
3. For an IDE test, launch a separate process with isolated user-data and
   extensions directories as well as HOME. After verifying `cursor --help`
   accepts the flags on that version, the command is:

   ```bash
   env -i PATH="$PATH" HOME="$probe_case/home" TMPDIR="$probe_case/tmp" \
     XDG_CONFIG_HOME="$probe_case/config" XDG_CACHE_HOME="$probe_case/cache" \
     XDG_DATA_HOME="$probe_case/data" XDG_STATE_HOME="$probe_case/state" \
     cursor --new-window --user-data-dir "$probe_case/user-data" \
     --extensions-dir "$probe_case/extensions" "$probe_case/project"
   ```

   Do not reuse a running real-profile IDE window. If the IDE hands off to an
   existing process, cannot isolate credentials, or loses the administered
   team policy, stop that cell and retain `unverified` with the exact reason.
   A clean profile without the required effective policy is not a valid test.

4. Test CLI separately using the kit's environment prefix and:

   ```bash
   cursor-agent --version
   cursor-agent --help
   cursor-agent -p --mode ask 'Return the instruction sentinel.'
   ```

   Record `interface: cli` for CLI observations. IDE observations need a
   separately ratified interface identity/record location; do not overwrite
   CLI evidence or pretend the results are interchangeable.

## Per-cell sequence

Use a fresh isolated case for each supported candidate combination, one role
at a time. Test native user/project, file user-explode/user, and file
repo-materialize/project. Record the other two mode/scope pairs as undefined
in the draft engine model rather than silently changing scope.

1. **Install:** copy the complete `probe-sentinel` package for native tests
   into exactly one candidate directory below. For file modes copy only the
   role payload to the corresponding candidate path. Do not use `--plugin-dir`
   to prove automatic loading from `plugins/local`.

   | Role           | User candidate                            | Project candidate                               |
   | -------------- | ----------------------------------------- | ----------------------------------------------- |
   | native package | `~/.cursor/plugins/local/probe-sentinel/` | `project/.cursor/plugins/local/probe-sentinel/` |
   | instruction    | `~/.cursor/rules/probe.mdc`               | `project/.cursor/rules/probe.mdc`               |
   | skill          | `~/.cursor/skills/probe-skill/`           | `project/.cursor/skills/probe-skill/`           |
   | specialist     | `~/.cursor/agents/probe-specialist.md`    | `project/.cursor/agents/probe-specialist.md`    |
   | workflow       | `~/.cursor/commands/probe-workflow.md`    | `project/.cursor/commands/probe-workflow.md`    |
   | lifecycle      | isolated user `hooks.json` candidate      | `project/.cursor/hooks.json` candidate          |
   | integration    | `~/.cursor/mcp.json`                      | `project/.cursor/mcp.json`                      |

   Here `~` means the throwaway HOME. These are **candidates**, not supported
   paths. For hooks, consult that installed host's schema and record the exact
   translation to the Python sentinel; do not assume Claude's SessionStart
   schema is accepted. If no safe documented mapping exists, retain unverified
   rather than inventing a working hook projection.

   For MCP, write `{"mcpServers":{"probe-integration":{"command":"python3",
"args":["<isolated-copy>/mcp/sentinel.py"]}}}` with the actual scratch path.
   No dependency installation or real project edits are needed.

2. **Reload:** quit only the isolated host, start a new process, open the
   disposable project, and re-confirm the effective import-disabled policy.
3. **Invoke:** use the host's explicit skill/command/agent invocation UI if
   available. Ask it to return only that item's sentinel; never include the
   expected token in the prompt. For instructions ask `Return the instruction
sentinel.` For hooks check `$TMPDIR/probe-hook.log`. For MCP capture the
   host's server listing; tool execution is optional and separately recorded.
   Record the exact prompt, displayed role name, tool trace and trimmed output.
4. **Restriction control:** with `disable-model-invocation: true` still in the
   skill, request the skill's purpose without naming it, then explicitly
   invoke it. A token after automatic selection demonstrates an invocation
   loss. A single non-selection alone does not prove enforcement. Compare a
   flag-free copy as a control and record host discovery/metadata too.
5. **Remove:** delete only the owned scratch payload/registration. Restart
   the isolated host and verify the item is no longer discoverable or
   invocable. Check config keys and cache trees separately; an empty list does
   not establish cache removal. Delete the entire owned case root afterwards.

## Cross-reads and policy markers

1. In separate cases put the skill only in isolated `~/.claude/skills`, then
   only in `~/.agents/skills`, with no `.cursor/skills` copy. Reload and invoke
   each, recording the host's loaded path. Then place copies in all roots and
   record whether discovery has duplicates. Do not infer repeated execution
   merely from repeated discovery.
2. With policy confirmed active, inventory **paths, keys, value types and
   digests only** in the isolated user-data and known system-managed policy
   locations. Compare against an authorized non-policy control if available.
   Never dump a settings file, credential store or entire organization policy.
3. For every proposed marker, record exact path/key, effective value,
   precedence and host version. If the policy is server-supplied and no disk
   marker can be established, write `not determinable: server policy; no
stable on-disk marker observed`. Do not encode a guessed detection rule.
4. If permission permits a native control without policy, run it in another
   isolated profile and label it a control. It cannot certify the policy cell.
   The CLI's explicit `--plugin-dir` flag is also only a separate control, never
   a substitute for either automatic drop path test or an import-policy bypass.

## Evidence to return

Create one record per cell using [the draft format](evidence-format.md). Preserve
all 15 fields; include the effective policy source in `policyMarkers` only when
actually observed. Record exact commands and exit codes, or an IDE action and
the actual observed result; do not invent process exit codes for UI actions.
If the draft needs UI action outcomes or `interface: ide`, have #565/#585 define
that extension before claiming schema validation. Until then preserve the
human transcript separately and leave the CLI cell unverified.

Expected **pending** CLI record (the strings below are placeholders, not data):

```yaml
host: cursor
interface: cli
version: REPLACE_WITH_ACTUAL_VERSION
os: REPLACE_WITH_OS_ARCH
role: skill
scope: project
mode: repo-materialize
state: unverified
lostFields: []
observed: absent
policyMarkers: []
checkedOn: 2026-11-01
recheckBy: 2027-02-01
steps:
  - phase: invoke
    command: not run
    exitCode: null
    output: Requires maintainer-run policy machine
notes: 'Reason: requires maintainer-run policy machine; no result submitted.'
```

Replace placeholders and dates, append install/reload/invoke/remove/verify
steps with the **actual** command results, and change state only as warranted.
`supported` needs `observed: invoked`, preserved semantics and cleanup evidence.
Use `policy-blocked` only for a demonstrated policy denial; auth failure,
missing isolation or an untested path remains unverified. Listed-only MCP stays
partial/discovered under this spike's conservative rule.

Finally compare the real config snapshots. Report changed paths/mtimes/digests
without contents and without restoring over other sessions. Purge the temporary
parent, auth copies, logs and IDE profile; confirm absence. Return sanitized
records, the human transcript, and the configuration comparison summary to
the maintainer; do not publish or edit downstream issues from the probe.
