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
`plugin.json` when emitted) are **generated adapters** behind a CI drift
gate, marked do-not-edit.

The README rewrite (issue #371) states the catalog is harness-agnostic by
construction — host adapters are build outputs. Contributors edit
`bundles.yaml` (and vendor registry entries), then run
`scripts/generate_marketplace.py`. Validation fails if any emitted
adapter is stale or missing.

`$generated` lives where each host schema allows it: top-level on Claude
marketplace JSON; under `metadata` on Cursor (root
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

[lab-decisions]: https://github.com/lgtm-hq/plugin-engine-lab/blob/main/DECISIONS.md
