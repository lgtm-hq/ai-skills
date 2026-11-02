# Host evidence format

This is the #563 research format, ratified by
[ADR 0009](../adr/0009-capabilities-and-parity.md); production schema implementation
belongs to issue #585. It changes no gateway support table. Each record describes
one tested envelope and its semantics on one host version and interface, rather
than promising support for every payload of that role.

The original CLI set has 108 records: three hosts × six roles × two scopes ×
three modes. The separate Cursor IDE extension below adds 72 records, for 180
total; interface and policy dimensions never overwrite the original identities.
`user-explode/project` and `repo-materialize/user` are deliberately recorded as
unverified: #581 does not define these combinations. They are inventory cells,
not proposed routes. User and project are distinct from Claude's additional
`local` setting, whose supplementary results live in the command log.

| Field           | Type and meaning                                                                                        |
| --------------- | ------------------------------------------------------------------------------------------------------- |
| `host`          | `claude-code`, `codex`, `cursor`                                                                        |
| `interface`     | `cli` for the original run; `ide` only in the separate extension below                                  |
| `version`       | Exact installed version string                                                                          |
| `os`            | OS and architecture: `linux-x86_64` or measured `darwin-arm64`                                          |
| `role`          | `skill`, `instruction`, `specialist`, `workflow`, `lifecycle`, `integration`                            |
| `scope`         | `user` or `project`                                                                                     |
| `mode`          | `native-plugin`, `user-explode`, `repo-materialize`                                                     |
| `state`         | One of the seven states below                                                                           |
| `lostFields`    | Losses: `invocation`, `activation`, `permissions`, `scope`; suspected losses must be qualified in notes |
| `observed`      | `invoked`, `discovered`, `absent`                                                                       |
| `policyMarkers` | CLI: observed markers; Cursor IDE policy: public setting name only                                      |
| `checkedOn`     | ISO date of observation or explicit assessment of why no probe ran                                      |
| `recheckBy`     | ISO date after `checkedOn`, at most six calendar months later                                           |
| `steps`         | CLI: nonempty `{phase, command, exitCode, output}` list; IDE exceptions below                           |
| `notes`         | Scope, semantic limits, cleanup caveats; `unverified` includes `Reason:`                                |

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
| `policy-blocked`       | Engine policy guard, demonstrated host denial, or sourced owner definition below                                |
| `source-unportable`    | Demonstrated source requirement cannot survive the projection                                                   |
| `adapter-missing`      | The tested host route is absent, or its necessary projection does not exist                                     |

`supported` always requires `observed: invoked` and no demonstrated field loss.
`partial` requires `observed: invoked` or `discovered`; `absent` cannot establish
partial behavior.
The Cursor user-explode skill has a suspected `invocation` loss: a token was
returned without naming the skill, but skill invocation versus file search is
unconfirmed. It is `partial`; the restriction is not established.
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
The [owner
decision](https://github.com/lgtm-hq/ai-skills/issues/563#issuecomment-6558530548)
defines Cursor policy outcomes using public documentation and personal-Cursor
results, as described below and in the [checklist](cursor-probe-checklist.md).
No employer-managed machine is probed or organization policy data collected.
Adapter tiers follow ADR 0009. This historical format has no `tier` field;
Issue #585 implements production adapter qualification. An engine tracked-file guard
can yield `policy-blocked` under [ADR 0010](../adr/0010-adapters-and-delivery-modes.md).
That engine decision is separate from a host-policy claim, which still requires
measured denial or an explicit sourced owner attestation.

## Cursor IDE and policy extension

ADR 0009 adopts this minimal IDE/policy extension from the owner's answered
decision. Production schema implementation remains #585.
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
personal cells explain the undefined mode/scope pair for which no check exists.
Measured `supported` requires an observed invocation token, all five phases,
observed removal/verification and preserved semantics. A derived supported
file-policy cell must reference a measured supported personal cell; it cannot
claim an independent execution or exceed that source's state/observation/losses.

The [owner
record](https://github.com/lgtm-hq/ai-skills/issues/563#issuecomment-6558530548)
and [Cursor public docs](https://cursor.com/docs/plugins#test-plugins-locally)
are the sources for all twelve native-plugin policy definitions. Those records
use `state: policy-blocked`, `observed: not-measured`, empty empirical steps,
and `evidence.kind: owner-attestation`. This is **by owner attestation and
definition**, not a policy-host measurement. `policyMarkers` contains only
`Allow Local Plugin Imports`; the source links live in `evidence.sources`.
No guessed on-disk policy detector follows from that public setting name.

The 24 file-policy cells use `evidence.kind: owner-derived` and cite the owner
decision plus the exact matching personal-cell path. The defined routes inherit
`ue-<role>` (user-explode/user) or `rm-<role>` (repo-materialize/project) from the
returned personal run, including its suspected loss. The twelve undefined
file-mode pairs remain unverified under #581, with null version/OS and no
measured observation. The other 24 personal cells are measured on Cursor IDE
3.27.22, darwin-arm64, macOS 27.2 on 2026-11-01. Six project native-plugin cells
are `adapter-missing/absent`; all six user native-plugin roles invoked.

## Raw evidence and rechecks

Returned probe files under `evidence/cursor/raw/` are **WRITE-ONCE** snapshots.
Never edit, normalize, reformat or replace an existing file, even to correct a
run note. Add a new file for a new run and append its SHA-256 and relative path
to [raw/INDEX.sha256](evidence/cursor/raw/INDEX.sha256). The pytest integrity check
fails for a changed or missing indexed file or an unindexed JSON snapshot.
The 2026-11-01 snapshot contains 41 checks plus hook/MCP sentinel logs; the run
was resumed by hand in the same record format. Its `*-removed` and `final-clean`
answers are the maintainer's removal observations; it contains no automatic
hook-boundary or scratch-purge status. Do not invent these from later kit tests.

The exact supplied script is archived at
[`cursor-macos-probe.sh`](../../tests/fixtures/host-probe/cursor-macos-probe.sh).
It predates the R6 controls; the maintained
[`cursor-macos-probe-driver.sh`](../../tests/fixtures/host-probe/cursor-macos-probe-driver.sh)
retains them and includes the canonical path, keychain restoration and This Mac
prompt. The archival lint exception is documented in
[CONTRIBUTING.md](../../CONTRIBUTING.md). Neither script's offline tests establish
new host evidence.

Owner policy requires a recheck after a host major/minor version change, an
adapter change, or the six-month maximum, whichever comes first. Re-probe only
the affected cells; #585 implements these triggers and expiry handling. The
2026-11-01 Cursor assessments use `recheckBy: 2027-05-01`. #620 adds the unattended
`cursor-agent` probe, with a separate CLI identity; it does not replace this IDE
evidence. ADR 0009 ratifies the minimal `interface: ide` and policy extension.

Paths in committed evidence are home-relative aliases (`~/probe/...`) or
repository-relative paths. Tokens, auth contents, personal absolute paths,
account information and machine names are excluded. Private snapshots contain paths,
mtimes and SHA-256 digests, including
credential-file fingerprints. Never publish these inventories or their aggregate
digests; publish counts and scoped limitations only. Delete private inventories
promptly after comparing and retaining sanitized evidence.

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

The maintained driver requires a prior invocation of each removed hook tag
before absence can be verified; a never-fired hook stays unverified. Its
post-exit isolation/scope checks do not certify host caches or same-version
updates. These offline changes never upgrade the returned snapshot.

`uv run pytest tests/test_parity_evidence.py` checks the complete field set,
types, vocabulary, dates, redaction, filename identities, Cartesian coverage,
and the invocation/cleanup requirements for supported cells. It is offline and
never executes a host. Expiry enforcement and the production parity schema
remain #585 work.
