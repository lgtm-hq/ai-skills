# Draft host evidence format

This is the #563 research format, pending ADR 0009 (#565) and the #585
implementation. It changes no gateway support table. A record describes one
tested envelope and its semantics, on one host version and interface, rather
than promising support for every possible payload of that role.

The original CLI set has 108 records: three hosts × six roles × two scopes ×
three modes. The separate Cursor IDE extension below adds 72 records, for 180
total; interface and policy dimensions never overwrite the original identities.
`user-explode/project` and `repo-materialize/user` are deliberately recorded as
unverified: #581 does not define these combinations. They are inventory cells,
not proposed routes. User and project are distinct from Claude's additional
`local` setting, whose supplementary results live in the command log.

| Field           | Type and meaning                                                                |
| --------------- | ------------------------------------------------------------------------------- |
| `host`          | `claude-code`, `codex`, `cursor`                                                |
| `interface`     | `cli` for the original run; `ide` only in the separate extension below          |
| `version`       | Exact installed version string                                                  |
| `os`            | OS and architecture, here `linux-x86_64`                                        |
| `role`          | `skill`, `instruction`, `specialist`, `workflow`, `lifecycle`, `integration`    |
| `scope`         | `user` or `project`                                                             |
| `mode`          | `native-plugin`, `user-explode`, `repo-materialize`                             |
| `state`         | One of the seven states below                                                   |
| `lostFields`    | List of demonstrated losses: `invocation`, `activation`, `permissions`, `scope` |
| `observed`      | `invoked`, `discovered`, `absent`                                               |
| `policyMarkers` | CLI: observed markers; Cursor IDE policy: public setting name only              |
| `checkedOn`     | ISO date of observation or explicit assessment of why no probe ran              |
| `recheckBy`     | ISO date strictly later than `checkedOn`; not a support extension               |
| `steps`         | Nonempty list of `{phase, command, exitCode, output}` mappings                  |
| `notes`         | Scope, semantic limits, cleanup caveats; `unverified` includes `Reason:`        |

Step phases are `install`, `reload`, `invoke`, `remove`, `verify`. Commands may
reference numbered commands in [the log](probe-log.md), whose argv and trimmed
outputs are preserved. File placement and whole-root purge refer to the
[kit recipes](../../tests/fixtures/host-probe/README.md). A fresh host process
is a reload. An integer exit code is the captured process result; `124` denotes
the harness timeout. `null` means not run, permitted only for `unverified`.
Explicitly labelled recipe steps use their enclosing Python driver's exit 0
for successful filesystem operations, rather than claiming a separate host
process ran. The log separately labels three successful RPC responses whose
server process shutdown exit codes were not captured.

| State                  | Meaning                                                                                                         |
| ---------------------- | --------------------------------------------------------------------------------------------------------------- |
| `supported`            | Invoked with the tested semantics preserved; successful remove and verification recorded                        |
| `partial`              | Some behavior observed, but a semantic loss, discovery-only result, or incomplete semantic verification remains |
| `unverified`           | Not safely or conclusively tested; a reason is mandatory                                                        |
| `platform-unavailable` | Tested prerequisite absent on this platform; no inference from another OS                                       |
| `policy-blocked`       | Demonstrated denial, or the explicitly sourced Cursor owner definition below                                    |
| `source-unportable`    | Demonstrated source requirement cannot survive the projection                                                   |
| `adapter-missing`      | Host route established but the necessary projection does not exist                                              |

`supported` always requires `observed: invoked` and no demonstrated field loss.
`partial` requires `observed: invoked` or `discovered`; `absent` cannot establish
partial behavior.
The issue allows MCP listing as evidence; these records conservatively use
`partial/discovered` for listed entries, even a Connected entry, rather than
labelling discovery as invocation. `absent` with `unverified` means **no
observation was obtained**, not a measured claim that the host cannot load it.
An empty `lostFields` is not proof of fidelity in a partial/unverified record.

An exit 1 model request can still trigger a lifecycle hook. The independently
checked sentinel log, with a successful inspection step, proves the hook ran;
it does not prove the requested skill ran. Never transfer that evidence to
another role. Likewise, an installed plugin is not a discovered specialist.

Do not infer policy from the presence of a plugin directory, an empty marker
list or authentication failure. The original CLI records do not assess policy.
The [owner decision](https://github.com/lgtm-hq/ai-skills/issues/563#issuecomment-6558530548)
defines Cursor policy outcomes using public documentation and personal-Cursor
results, as described below and in the [checklist](cursor-probe-checklist.md).
No employer-managed machine is probed or organization policy data collected.
No `tier` field is ratified here;
Issue #587's proposed `tier: verified` belongs to #565/#585, not an invented
spike field.

## Cursor IDE and policy extension

This is the minimal draft addition needed for the owner's answered decision,
flagged for #565 ratification and #585 implementation, not a production redesign.
Original filenames remain `evidence/<host>/<role>-<scope>-<mode>.yaml`, with
implicit `interface: cli` and policy unassessed. New filenames are
`evidence/cursor/ide/<policy>/<role>-<scope>-<mode>.yaml`, where policy is
`none` (personal run) or `local-plugin-import-disabled` (owner derivation).
Each has all 36 role/scope/mode identities, including the twelve undefined pairs.
Full identity is `(host, interface, policy, role, scope, mode)`.

IDE records retain the base fields and add exactly `policy` and `evidence`:

| Field                  | Meaning                                                                                             |
| ---------------------- | --------------------------------------------------------------------------------------------------- |
| `policy`               | `none` or `local-plugin-import-disabled`                                                            |
| `evidence.kind`        | `pending`, `measured`, `owner-attestation`, or `owner-derived`                                      |
| `evidence.sources`     | Nonempty list of source URLs or repository paths; measured JSON references include actual check IDs |
| `evidence.derivedFrom` | Repository-relative matching personal-cell path for file-policy derivations; otherwise empty list   |

`version` and `os` are null until a personal IDE measurement exists; null also
applies to native policy definitions, which make no version-specific measured
claim. `observed: not-measured` is permitted only for pending IDE evidence and
owner definitions. It explicitly avoids interpreting `absent` as an empirical
result. The assessment date is not an execution date for these records.

IDE steps use `{phase, action, outcome, output}` with the existing five phases
and `outcome: pending|observed|not-run`, rather than CLI commands/exit codes.
Owner-attested and owner-derived records have no empirical steps. Pending
personal cells name their exact outstanding JSON check in an invoke action.
Measured `supported` requires an observed invocation token, all five phases,
observed removal/verification and preserved semantics. A derived supported
file-policy cell must reference a measured supported personal cell; it cannot
claim an independent execution or exceed that source's state/observation/losses.

The [owner record](https://github.com/lgtm-hq/ai-skills/issues/563#issuecomment-6558530548)
and [Cursor public docs](https://cursor.com/docs/plugins#test-plugins-locally)
are the sources for all twelve native-plugin policy definitions. Those records
use `state: policy-blocked`, `observed: not-measured`, empty empirical steps,
and `evidence.kind: owner-attestation`. This is **by owner attestation and
definition**, not a policy-host measurement. `policyMarkers` contains only
`Allow Local Plugin Imports`; the source links live in `evidence.sources`.
No guessed on-disk policy detector follows from that public setting name.

The 24 file-policy cells use `evidence.kind: owner-derived` and cite the owner
decision plus the exact matching personal-cell path. The defined routes await
`ue-<role>` (user-explode/user) or `rm-<role>` (repo-materialize/project) from
`cursor-probe-results-*.json`; the other pairs remain undefined by #581.
Until those measurements exist, file-policy cells stay unverified with null
version/OS and no measured observation. All 36 personal IDE cells currently
remain unverified. The supplied script and offline tests are source validation,
not returned evidence. No personal version, observation or cleanup is invented.

Paths in committed evidence are home-relative aliases (`~/probe/...`) or
repository-relative paths. Tokens, auth contents, personal absolute paths,
account information and machine names are excluded. Private snapshots contain
only paths, mtimes and SHA-256 digests and must never be committed.

The original run's protected-config counts (5,372 matching of 5,381 selected
entries, nine changes) apply only to the old collector, which omitted paths
containing runtime-like names anywhere, including legitimate nested payloads.
The [cleanup comparison](README.md#cleanup-and-protected-configuration) does
not establish whole protected-inventory immutability. R2's host-root-only
exclusions have offline disposable-HOME coverage, with no live remeasurement
or retroactive certification of the corrected inventory. Record cleanup
references retain this limitation; they do not upgrade host evidence.

The current collector rejects symbolic links throughout the protected scope
(including skill/plugin directories, host roots, payload ancestors, dangling
links and cycles), linked HOME/ancestors and unsupported file types. Known
excluded runtime roots are still outside the inventory. Listing, stat and read
errors fail collection; they are never treated as absent entries or skipped.
Use physical HOME paths, fresh before/after destinations and require successful
collector exits before comparison. Failure means the comparison is incomplete,
not unchanged; preserve the error privately and report the limitation without
publishing contents. Successful collection covers only the documented selected
suffixes/names and is not atomic against concurrent writes. Link/error handling
was verified only offline in disposable homes, with no live remeasurement or
upgrade to the old counts, records or D001–D003 traces.

`uv run pytest tests/test_parity_evidence.py` checks the complete field set,
types, vocabulary, dates, redaction, filename identities, Cartesian coverage,
and the invocation/cleanup requirements for supported cells. It is offline and
never executes a host. Expiry enforcement and the production parity schema
remain #585 work.
