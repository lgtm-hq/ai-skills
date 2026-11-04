# Deterministic capability artifacts

The Python build plane owns resolution. `ai-skills-engine build` (also
`ai-skills-engine bake artifacts`) consumes the same inventory, selection and
provenance results as `plan`. An invalid selection cannot publish an artifact.
Nothing in a vendor tree is executed.

```sh
uv run ai-skills-engine build --vendor-tree vendor=../pinned-vendor
uv run ai-skills-engine build --vendor-tree vendor=../pinned-vendor --write-digests
uv run ai-skills-engine build --vendor-tree vendor=../pinned-vendor --check
```

`--vendor-root` is an equivalent spelling; nested inputs use slash-qualified
aliases, for example `publisher/upstream=../upstream`. Inputs are declarations of
locally available pinned snapshots, with the same assurance boundary as inventory
and plan. `--fetch-vendors` explicitly authorizes the existing bounded pinned
fetcher. The default command never acquires missing inputs. Neither path runs
vendor hooks, package installers or scripts.

Artifacts are emitted into `dist/artifacts/`, atomically replacing the previous
complete generation. `--output` selects another destination. The compatibility
`plugins-baked/` tree and its existing bake/check commands retain their format.
The compatibility baker also accepts `--vendor-tree ID=PATH`.

Each qualified package `publisher/package` has a `publisher--package.tar` and
`publisher--package.tar.sha256`. Double hyphens cannot occur in manifest ID
segments, so this encoding distinguishes publishers without collisions. Each tar
contains its package's selected capabilities and their complete hard dependency
closure, including capabilities from other packages. `index.json` at the output
root inventories the complete selected catalog. Each tar has its own index with
`rootPackage` identifying the primary package and inventories of the actual
capabilities included in that tar.

`schemas/artifact-index.v1.schema.json` is canonical. Package synchronization
generates the Python resource and npm schema copy. The writer validates against
its installed resources, resolving the existing lineage schema locally, without
fetching schemas. `artifactFormat`, manifest `apiVersion`, engine version and
package versions are separate. Local package versions come from `pyproject.toml`
or `x-version`, with `0.0.0-local` for unversioned local inputs; vendor versions use
the existing pin-derived version function.

A capability lives at `packages/<publisher>/<package>/<role>/<id>/`. Its index
contains its source and output tree digests, direct `requires` and `related`,
precomputed sorted closure membership, SCC units, host attributes and names,
resource copies, complete lineage, legal obligations and portability losses.
Closure includes the capability itself. Singleton SCCs are also explicit units.
Soft edges never expand selection. Consumer exclusions, origin denies, roles,
identity migrations and collision decisions retain the selection engine's rules.

Package inventories also contain standalone selected resources under
`packages/<publisher>/<package>/resource/<id>/`. A package containing only pulled-in
resources receives its own tar. Capability-local resource copies remain the
projection inputs; standalone copies preserve the complete resource inventory.

Resources declared by each capability are copied into that capability's
`_shared/<resource-publisher>/<source-relative-path>`. Resources already inside
the capability stay there. Resources from one publication retain their relative
layout, so sibling script/data dependencies survive copying. Every capability
gets its own copies and resource lineage; the builder never deduplicates equal
bytes across capabilities. Source digests and chains are retained alongside
output digests after reference rewriting.

Only CommonMark destinations and explicitly declared scalar fields are rewritten.
The CommonMark parser must prove each candidate's role by reparsing the edited
source. Prose, fences, code spans, link labels and titles retain their bytes.
Unsupported or demonstrably unrewritable references record `source-unportable`
with reasons for `user-explode` and `repo-materialize`. This is a static source
assessment, never a claim of host parity. It cannot prove arbitrary script
behavior. Portable capability roots pass the ADR 0006 link checker in isolation.

Declare scalar fields with the capability/resource extension `x-resource-paths`:

```yaml
x-resource-paths:
  config.json: ['/script', '/files/0']
  SKILL.md: ['/metadata/helper']
```

Pointers follow RFC 6901. JSON/YAML pointers address the file root; Markdown
pointers address frontmatter. Files must belong to the declared payload. Ordinary
string scalars are supported; aliases, anchors, tags and block scalars receive a
portability diagnostic. Rewrites change only scalar spans, preserving neighboring
source. These declarations never create a resource or dependency edge.

`NOTICE.md` and `LICENSES/<percent-encoded-origin>.txt` cover only ancestry present
in the tar, including resource origins and every re-export hop. Available root,
payload and ancestor license/notice texts propagate verbatim. The known generated
catalog NOTICE is regenerated for shipped origins; authored notice text is kept.
Missing declared license metadata/text remains `NOASSERTION`; the builder does
not invent a license grant. Legal files receive bounded reads and ingestion
content checks before publication.

Tar entries are sorted PAX records. Files use inventory's canonical 0644/0755
modes; directories use 0755. uid/gid/mtime are zero, owner names empty and extended
times absent. Sidecars identify the SHA-256 of the **uncompressed** tar. That digest
never appears in either index; it cannot include itself.

`--write-digests` generates `artifact-digests.json` with per-package tree and tar
digests plus a fingerprint of the local author inputs. `--check-inputs` checks that
fingerprint offline in a fresh clone. It does not authenticate missing vendor
bytes. `--check` rebuilds all packages in private scratch and compares the entire
reviewed commitment without modifying output. Publish must run this full check;
a matching local input fingerprint alone cannot authorize release. Unknown digest
formats and duplicate keys fail closed. No bake payload is committed.

`recommend_semver(before, after)` returns a `SemverAdvice` record with `level` and
sorted `reasons`. Removals, broken hard dependencies and widened invocation,
activation or permissions recommend major; additions minor; content/metadata
changes patch; equal capability inventories none. Unknown permission/activation
changes are conservatively major because literal comparison cannot prove
arbitrary pattern containment. Advice does not reject a build or enforce a bump.

`tests/fixtures/artifacts/golden/` contains a complete consumable tar, sidecar and
catalog index built from the adjacent synthetic `source/` publication. Its cycle,
shared copies, invocation restriction, structural rewrites and source portability
losses are inputs for downstream verification/filtering tests in #578.

## Host envelopes

`ai-skills-engine generate` derives every host plugin envelope and marketplace
from an artifact index and a kept-capability set; see the ADR 0002 amendment.
`--index dist/artifacts/index.json --output DIR` writes a built envelope tree,
with `plugins/<name>/` envelopes and Claude, Cursor and Codex marketplaces, for
every exported package. `--exclude CAPABILITY_ID` and `--host` filter that tree.
The rules are `schemas/envelope-rules.v1.json`; `tests/fixtures/envelopes/`
holds its goldens. The tree contains envelopes only: the install plane places
each kept capability's payload under `skills/` or `agents/` beside them.
