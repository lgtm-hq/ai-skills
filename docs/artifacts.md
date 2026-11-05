# Deterministic capability artifacts

The Python build plane owns resolution. The artifact writer consumes the same
inventory, selection and provenance results as `plan`. An invalid selection cannot
publish an artifact. Nothing in a vendor tree is executed.

```sh
uv run ai-skills-engine lock            # resolve changed inputs, fetch missing sources
uv run ai-skills-engine lock --check    # no writes; fail if the lock is stale
uv run ai-skills-engine lock --fetch    # populate the cache for the existing lock only
uv run ai-skills-engine build           # offline: lock + cache -> dist/artifacts/
uv run ai-skills-engine bake artifacts --vendor-tree vendor=../pinned-vendor
```

`ai-skills-engine build` is the frozen, reproducible build described under
[Resolution lock and source cache](#resolution-lock-and-source-cache).
`bake artifacts` is an explicit-input development writer: it builds from the
manifest and locally supplied snapshots and never reads, writes or fetches for the
lock. `--vendor-root` is an equivalent spelling of `--vendor-tree`; nested inputs
use slash-qualified aliases, for example `publisher/upstream=../upstream`.
Supplied inputs are declarations of locally available pinned snapshots, with the
same assurance boundary as inventory and plan. No path runs vendor hooks, package
installers or scripts.

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
A capability or standalone resource whose origin publication has no manifest
records `"identity": "consumer-asserted"`: a consumer mapping, not the upstream,
asserted that identity.
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

## Resolution lock and source cache

`ai-skills.lock` is committed JSON with sorted keys, 2-space indentation and a
trailing newline. It contains no timestamps, absolute paths, usernames or
hostnames. It records everything needed to rebuild the artifacts byte for byte:

```json
{
  "lockVersion": 1,
  "builder": { "engineVersion": "0.30.9", "artifactFormat": 1 },
  "manifest": {
    "apiVersion": "ai-skills.dev/v1",
    "digest": "sha256:…",
    "inputsDigest": "sha256:…"
  },
  "vendors": [
    {
      "id": "anthropics",
      "repo": "anthropics/skills",
      "sha": "…",
      "sourceDigest": "sha256:…",
      "filters": { "include": [], "exclude": [] }
    }
  ],
  "packages": [
    {
      "id": "anthropics/document-skills",
      "version": "…",
      "artifactDigest": "sha256:…",
      "treeDigest": "sha256:…",
      "capabilities": [{ "id": "…", "closure": ["…"], "lineage": [] }],
      "resources": [{ "id": "…", "lineage": [] }]
    }
  ]
}
```

- `manifest.digest` hashes the canonical JSON of the parsed `ai-skills.yaml`, so
  reordering YAML keys or reformatting does not change the lock.
  `manifest.inputsDigest` fingerprints the declared local payloads, legal files,
  `pyproject.toml` and builder sources; it is the offline checkout drift gate.
- `vendors` lists every pinned import, including nested slash-qualified pins.
  `sourceDigest` is the SHA-256 of a canonical uncompressed tar of the extracted
  tree (sorted PAX entries, 0644/0755 file modes, link targets verbatim, no
  owners or times), never of the forge's compressed archive.
- `packages` carries each package's external tar digest and tree digest. Each
  capability's sorted `closure` (capabilities and resources) and its `lineage`
  chains are copied verbatim from the built index. Standalone resources,
  including artifact-only `_shared` resources declared in the index
  `resources[]`, carry their index lineage. Equal bytes never establish lineage.

Reading is strict: an unknown `lockVersion`, an unknown key, a duplicate key or a
malformed value fails with a specific message and is never read on a best-effort
basis. `build` and `lock --check` also require the canonical byte encoding.

The source cache lives at
`${AI_SKILLS_CACHE:-${XDG_CACHE_HOME:-~/.cache}/ai-skills}` (a relative
`XDG_CACHE_HOME` is ignored). It holds `sources/sha256-<digest>.tar` canonical
source trees plus `refs/<owner>/<repo>/<revision>`, which maps each pinned
revision to its digest. Every read re-verifies the digest, and a corrupted entry
fails with its own message instead of being refetched silently. Writes go to a
temporary file, are fsynced and then renamed, so concurrent CI jobs can share a
cache. Acquired trees pass the existing structural ingestion checks before they
are stored, and cold and warm paths extract the same canonical bytes. The
compatibility vendor bake and `inventory --fetch-vendors` read pinned trees
through the same cache.

- `lock` re-resolves only manifest entries whose repository, SHA or filters
  changed and never moves an existing pin; `repin` moves pins (see
  [Vendor re-pin](../CONTRIBUTING.md#vendor-re-pin)). Unchanged pins
  must reproduce their locked `sourceDigest`. It fetches missing sources (or
  seeds the cache from `--vendor-tree ID=PATH` snapshots), rebuilds all packages
  in private scratch and rewrites the lock only when its bytes change.
- `lock --fetch` fills the cache for the existing lock only, verifying each
  fetched tree against its `sourceDigest`.
- `lock --check` writes nothing. It fails on a builder, manifest or local-input
  change, then rebuilds from the cache alone and compares the complete lock.
  `--check --inputs-only` stops after the offline checks and needs no sources;
  `scripts/validate.sh` runs it.
- `build` works offline from the lock and cache. It refuses a stale lock and any
  missing or corrupted cache entry, naming the vendor and the `lock --fetch` fix.
  It replaces `dist/artifacts/` only when every rebuilt digest equals the lock.
  Network access during `build` is a bug.

CI's lock gate and `publish-npm.yml` run `lock --fetch`, `lock --check` and
`build`, so publishing fails closed if any `artifactDigest` differs. The engine
never reads or writes the v1 gateway install state (`ai-skills-lock.json` or
`~/.ai-skills/lock.json`); machine-local install receipts are a separate file.

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
each kept capability's payload under `skills/` or `agents/` beside them. Codex
has no repo-root slice projection: Codex copies the whole tree at `source.path`,
so its repo-root marketplace lists no package. Codex native delivery uses these
built `plugins/<name>/` trees (#384). Without `--index`, built output covers only
the publisher's own packages and prints a note naming any exported vendor
packages it omits.
