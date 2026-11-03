#!/usr/bin/env bash
# Run the strict gateway gate; acquisition happens before the offline unit suite.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

cd "$REPO_ROOT"
# Existing integration tests consume the canonical bake, never fetch in tests.
if [[ ! -f plugins-baked/BAKE.json ]]; then
  uv run --no-sync python scripts/bake_vendor_plugins.py
fi
uv run --no-sync python scripts/bake_vendor_plugins.py --check
package_version="$(bun -e 'console.log(require("./npm/ai-skills/package.json").version)')"
uv run --no-sync python scripts/ci/npm/sync_ai_skills_package.py --version "$package_version"
uv run --no-sync python scripts/ci/npm/sync_ai_skills_package.py --check --version "$package_version"

cd npm/ai-skills
bun install --frozen-lockfile
# The Python-only job has no Bun/node_modules. This prepared gate owns the
# mandatory production parser/extractor/updater controls; never acquire in tests.
UV_OFFLINE=1 uv run --no-sync pytest \
  "$REPO_ROOT/scripts/ci/npm/manifest_yaml_boundary_tests.py" \
  "$REPO_ROOT/scripts/ci/npm/manifest_renovate_tests.py"
bunx tsc --noEmit
bun test --coverage
bun run build:launcher
bun scripts/launcher-smoke.ts
bun scripts/check-pack.ts
