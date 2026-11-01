# Cursor personal macOS probe checklist

Human handoff for #563. The binding [owner decision](https://github.com/lgtm-hq/ai-skills/issues/563#issuecomment-6558530548)
replaces the earlier procedure. Probe **personal Cursor on a personal Mac only**,
in an isolated profile. No employer-managed machine is probed and no
organization policy names, values or sources are collected.

Cursor's [Test plugins locally documentation](https://cursor.com/docs/plugins#test-plugins-locally)
names **Allow Local Plugin Imports**. Under the owner's decision, native-plugin
policy cells are `policy-blocked` by definition, citing the decision and public
docs. This is owner attestation, not an empirical policy-host measurement.
File-mode policy cells follow the corresponding personal no-policy results;
they remain `unverified` until those exact results arrive. `policyMarkers`
references only the public setting name. Do not invent on-disk detection keys.

## Run the supplied source kit

Use [cursor-macos-probe.sh](../../tests/fixtures/host-probe/cursor-macos-probe.sh)
with stock macOS `/bin/bash` 3.2, an already installed personal Cursor, Python 3
and `shasum`. Run it from a scratch output directory, with the script addressed
by its absolute checkout path:

```bash
/bin/bash /path/to/checkout/tests/fixtures/host-probe/cursor-macos-probe.sh
```

Quit normal Cursor first. The script creates a private temporary HOME, project,
TMPDIR, XDG roots, user-data and extensions directories, and launches the direct
Cursor CLI in an empty environment with explicit storage paths. Sign in only
with the personal account in the isolated window. Check that it is the isolated
profile and that **Allow Local Plugin Imports** permits the native control.
Stop if a window is handed to an existing profile or isolation is unconfirmed.
HOME overrides are not a sandbox: macOS account services and Keychain can still
use the logged-in account. Do not copy credentials or complete settings homes.

The five phases cover user-explode/user, repo-materialize/project, native/user,
native/project and final removal. Each phase asks about all six roles, then
records removal after restart. Candidate native roots are isolated
`~/.cursor/plugins/local` and `project/.cursor/plugins/local`; the project root
is a candidate, not a supported route. File candidates are `rules`, `skills`,
`agents`, `commands`, `hooks.json` and `mcp.json` under isolated `.cursor`.
Additional AGENTS.md, cross-read and invocation-restriction controls are
supplementary checks, not extra Cartesian cells. Cross-read checks do not by
themselves establish duplicate discovery or execution.

Before each removal restart, the script records hook-log byte and line
boundaries. Complete the displayed fresh-chat prompt before answering the
removal question. The automatic removal check inspects only new entries for
the exact removed tag; old entries and the next phase's tag do not count.
`hookRemovalEvidence` retains the boundaries and actual removal status. A
skipped prompt or unreadable/truncated log leaves hook removal unverified.

Use a new agent chat for each check. Type only the prompt/invocation shown,
not the expected token. `y` means the stated check succeeded, `d` means listed
only, `n` means no, and `s` means skipped. Record uncertainties in a short note
without personal information. The script's JSON is a transcript, not an
automatic `supported` verdict: invocation semantics, removal, caches and config
must all be reviewed per cell. A failed request can still trigger a hook;
credit the independent hook log only to lifecycle. MCP process startup is not
a successful tool call. Non-selection once does not prove enforcement of
`disable-model-invocation`.

## Explicit isolated launch and hook inspection

The following equivalent launch skeleton documents the storage boundary for
manual follow-up. Use a fresh disposable `probe_case`, with its `project`
directory already prepared, in the personal Mac desktop session. Resolve the
installed direct `cursor` launcher on PATH before starting. Do not use `open -a`.

```bash
# Isolated IDE common setup
: "${probe_case:?Prepare the isolated case first}"
mkdir -p "$probe_case"/{home,tmp,config,cache,data,state,user-data,extensions}
probe_cursor() {
  env -i PATH="$PATH" HOME="$probe_case/home" TMPDIR="$probe_case/tmp" \
    XDG_CONFIG_HOME="$probe_case/config" XDG_CACHE_HOME="$probe_case/cache" \
    XDG_DATA_HOME="$probe_case/data" XDG_STATE_HOME="$probe_case/state" \
    ${probe_session[@]+"${probe_session[@]}"} \
    cursor --new-window --user-data-dir "$probe_case/user-data" \
    --extensions-dir "$probe_case/extensions" "$@" "$probe_case/project"
}
```

```bash
# macOS launch
(
  probe_session=()
  probe_cursor
)
```

The guarded array expansion works with `set -u` on Bash 3.2. Hook inspection
must use the case path explicitly: the child's TMPDIR assignment does not
change the parent shell's TMPDIR. The script uses this same isolated log
location, with a tag for each phase; the generic kit hook also writes there.

```bash
# Isolated hook inspection
cat "$probe_case/tmp/probe-hook.log"
```

After stopping the isolated process and saving sanitized results, remove only
the owned case (including its hook log), never an ambient runtime log:

```bash
# Isolated case cleanup
rm -rf "${probe_case:?Owned isolated case is required}"
test ! -e "$probe_case"
```

## Return evidence and keep #563 open

Return `cursor-probe-results-<timestamp>.json`. Review the sanitized output
locally before returning it; retain any original returned file unchanged.
No results have been received in this revision. Do not fill in a Cursor IDE
version, OS architecture, observation or exit status from the Linux CLI run.

The [draft format](evidence-format.md#cursor-ide-and-policy-extension) now gives
IDE/policy evidence a separate identity and provenance. For each measured cell,
carry the actual JSON check IDs, exact IDE version/OS/date, prompts, displayed
results, install/restart/removal and cleanup evidence into
`evidence/cursor/ide/none/`. UI actions use outcomes, not fabricated process
exit codes. Listed-only MCP is partial/discovered; missing or inconclusive
checks stay unverified with their reason. The two undefined mode/scope pairs
remain undefined under #581.

For `evidence/cursor/ide/local-plugin-import-disabled/`, retain the twelve
native-plugin definitions as owner-attested `policy-blocked` with no measured
observation. File records derive only from the matching `ide/none` cell and
cite the owner decision. Their current dependency is that cell's specific
personal JSON check (`ue-<role>` or `rm-<role>` for the defined file routes).
CLI records remain separate. #565 must ratify this minimal extension; #585
owns its production schema.

The script fingerprints selected real `.cursor`, `.claude` and `.agents`
regular files using paths and SHA-256 only. Its exclusions and size limit mean
this is not a complete inventory; diff-line counts are not distinct changed
files. Errors make comparison incomplete. No causality or no-residue claim
follows from a match. It does not read file contents into returned evidence or
restore over concurrent changes. The EXIT trap stops the isolated process and
purges scratch state; `--keep` explicitly retains private scratch state and
cannot prove cleanup. Before cleanup, even a failed final scan, comparison or
report collection saves available answers and logs to sanitized partial JSON.
`runStatus`/`incompleteReason` and
`configComparisonStatus`/`configComparisonReason` disclose incomplete work;
an unverified comparison has a null `realConfigChangedEntries` count.
`collectionErrors` names unavailable inputs without private exception text.
`cleanup` reports pending, purged, retained or unverified owned-scratch cleanup;
it does not establish host cache removal. Failures and handled interruptions
still exit nonzero. If writing the result file fails, sanitized JSON is printed
to stdout as a fallback. Inspect deletion and cache/config removal separately.
These transcript fields are input to #565, not a production schema redesign.

The source kit is complete, but returned personal JSON remains the owner gate.
This revision is **Part of #563**. It cannot close the issue or establish host
acceptance; the owner's merge order after #562 and personal-result requirement
still apply. Historical D001–D003 and old-collector-only counts remain unchanged.
