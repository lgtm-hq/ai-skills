# Draft host evidence format

This is the #563 research format, pending ADR 0009 (#565) and the #585
implementation. It changes no gateway support table. A record describes one
tested envelope and its semantics, on one host version and interface, rather
than promising support for every possible payload of that role.

There are 108 records: three hosts × six roles × two scopes × three modes.
`user-explode/project` and `repo-materialize/user` are deliberately recorded as
unverified: #581 does not define these combinations. They are inventory cells,
not proposed routes. User and project are distinct from Claude's additional
`local` setting, whose supplementary results live in the command log.

| Field           | Type and meaning                                                                |
| --------------- | ------------------------------------------------------------------------------- |
| `host`          | `claude-code`, `codex`, `cursor`                                                |
| `interface`     | `cli` for this run; CLI results do not certify an IDE                           |
| `version`       | Exact installed version string                                                  |
| `os`            | OS and architecture, here `linux-x86_64`                                        |
| `role`          | `skill`, `instruction`, `specialist`, `workflow`, `lifecycle`, `integration`    |
| `scope`         | `user` or `project`                                                             |
| `mode`          | `native-plugin`, `user-explode`, `repo-materialize`                             |
| `state`         | One of the seven states below                                                   |
| `lostFields`    | List of demonstrated losses: `invocation`, `activation`, `permissions`, `scope` |
| `observed`      | `invoked`, `discovered`, `absent`                                               |
| `policyMarkers` | Observed policy markers with their source; empty means none established         |
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
| `policy-blocked`       | Active policy demonstrably denied the tested route                                                              |
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
list, authentication failure, or this laptop's lack of managed policy. Cursor's
required policy-machine records remain unverified until the maintainer follows
the [checklist](cursor-probe-checklist.md). No `tier` field is ratified here;
Issue #587's proposed `tier: verified` belongs to #565/#585, not an invented
spike field.

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
