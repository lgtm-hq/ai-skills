# ADR 0002: Neutral canonical metadata; host manifests are generated adapters

- Status: Accepted
- Date: 2026-08-27
- Evidence: [plugin-engine-lab DECISIONS.md][lab-decisions]
  (Final Agreements item 1; multi-host manifest emission);
  Cursor root `additionalProperties: false` from issue #369

## Context

Each host wants a slightly different marketplace or plugin manifest.
Claude Code reads `.claude-plugin/marketplace.json`. Cursor and Copilot
also consume Claude-format marketplaces, but Cursor's own marketplace
schema is stricter (`additionalProperties: false` at the root and on
plugin entries). Hand-maintaining parallel JSON files drifts.

The lab proved hosts ignore foreign manifest dirs. Extra adapters are
optional mirrors, not a second authoring format. The repo's own metadata
(`bundles.yaml`, `vendors.yaml`, per-plugin fields) is the source of
truth.

## Decision

Canonical format is **neutral metadata**. All host dirs
(`.claude-plugin/`, `.cursor-plugin/`, `.codex-plugin/`, root
`plugin.json` when emitted) **shall be** generated adapters behind a CI
drift gate, marked do-not-edit. Issue #369 emits the Claude and Cursor
adapters; later hosts follow the same generator.

Issue #371 rewrites the README to state the catalog is harness-agnostic
by construction — host adapters are build outputs. Contributors edit
`bundles.yaml` (and vendor registry entries), then run
`scripts/generate_marketplace.py`. Validation fails if any emitted
adapter is stale or missing.

Issue #369 places `$generated` where each host schema allows it:
top-level on Claude marketplace JSON; under `metadata` on Cursor (root
`additionalProperties: false`).

## Consequences

- Never hand-edit generated manifests. Regenerators plus
  `git diff --exit-code` (the generator `--check` path) are the drift
  gate, not a second parser that compares files.
- Cursor/Copilot extra adapters may omit fields Claude uses (skills
  arrays, version on plugin entries) when the host schema forbids them.
  The group list still mirrors `bundles.yaml`.
- Release restamp (`scripts/update-readme-version.sh`) rewrites every
  generated adapter that carries a version, not only README pins.

## Amendment: the artifact index is the envelope input (2026-11-04)

Issue #575 replaces `bundles.yaml` as the generator input. Every host envelope
(root `plugin.json`, `.claude-plugin`, `.cursor-plugin` and `.codex-plugin`
plugin manifests, and the Claude, Cursor and Codex marketplaces) comes from
`ai_skills_engine.envelopes`. Its inputs are the artifact `index.json` from
[ADR 0011](./0011-manifest-provenance-locks-artifacts-trust.md) and a set of
kept capabilities. The index is the only capability input: roles, versions, tree
digests, `_shared` resources and closures. The publishing manifest supplies
presentation only: exports and their order, display names, descriptions, authors
and declared licenses. The field rules are data in
`schemas/envelope-rules.v1.json`, and goldens live in `tests/fixtures/envelopes/`.
This lets the install plane regenerate filtered envelopes byte for byte.

- `uv run ai-skills-engine generate` writes the committed repo-root marketplaces,
  and `--check` is their drift gate. `scripts/generate_marketplace.py` remains
  a compatibility shim. The publisher's index is built offline. Vendor
  envelopes use a complete `ai-skills-engine build` index through `--index`
  and `--output`.
- Repo-root entries may reference in-repo slices only while each sliced tree's
  digest equals the capability `treeDigest` in the artifact. They also cannot
  carry artifact-only resources. Otherwise generation fails and names the
  package that needs a built envelope.
- Skills and specialists project through the `skills/` and `agents/`
  directories. Any other role fails generation and names the capability until
  a host projection exists.
- Excluding a capability removes it from every envelope and marketplace entry.
  An emptied package disappears. A kept capability whose closure needs an
  excluded one fails.
- The Codex adapter is `.agents/plugins/marketplace.json` (no `$generated`
  field, since the evidence shows no open root). Its plugin manifest keeps the
  minimal `name`, `version`, `description` and `author` payload. The #563
  probe did not isolate any other Codex field. The rules record these cells as
  `unverified`.
- No committed Codex marketplace entry may deliver a tree other than that
  package's kept artifact tree. Codex copies the whole tree at `source.path`
  (`docs/parity/README.md`) and has no evidenced slicing field, so a `./` entry
  would install the entire repository, including unexported skills. The rules
  therefore set Codex `entries.slice` to `null`: the repo-root slice layout
  emits no Codex entry, and the committed `.agents/plugins/marketplace.json`
  lists no first-party package. It stays generated and drift-checked.
  `generate --layout slice --output` prints a note saying so. A Codex entry may
  point only at a plugin directory whose delivered tree is the package's kept
  artifact tree, as the built layout's `./plugins/<name>` entries do. So
  first-party Codex native delivery comes from the built layout (#384). The
  Cursor `./` entries keep today's bytes, as #575 requires; that is not a
  precedent for new hosts.
- Vendor bake per-plugin envelopes and their `--check` delegate to the same
  generator. `plugins-baked/` bytes are unchanged.

[lab-decisions]: https://github.com/lgtm-hq/plugin-engine-lab/blob/main/DECISIONS.md
