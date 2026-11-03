# Offline provenance fixture

X owns `x/tools:skill/plain` and `x/tools:resource/script`. Y explicitly re-exports
X's package, renames and transforms copies into its own capabilities, and
materializes the resource under `_shared/` while retaining its X resource ID.
Y's index carries the declared X/Y chains. Z imports Y and denies X; both Z
capabilities require the shared resource, so both fail with visible chains.

The synthetic pins are forty `a` characters for X and forty `b` characters for Y.
They identify deterministic test inputs; supplied snapshots retain the normal
pin-unverified warning. No fixture code may run. The Python resources raise
immediately if executed. No network is needed.

From the repository root:

```sh
uv run ai-skills-engine plan \
  --repo-root tests/fixtures/provenance/two-hop/z \
  --vendor-root y=tests/fixtures/provenance/two-hop/y \
  --vendor-root y/x=tests/fixtures/provenance/two-hop/x \
  --json
```

The expected exit status is 1. Remove Z's origin deny to obtain a valid plan.
`ai-skills.lineage.json` records hash the actual fixture payloads, including their
Git-like executable modes. Capability IDs and resource IDs survive resource copies
and declared name transformations; equal bytes alone never assign ancestry.
