#!/usr/bin/env bash
# Generate from the selected release using tooling from the workflow revision.
set -euo pipefail

tooling_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
repo_root=$(cd -- "${1:?Usage: generate_skills_manifest.sh RELEASE_ROOT [generator flags]}" && pwd)
shift
cd "$repo_root"

# Pre-package tags have a standalone stdlib generator and need no installation.
if [[ ! -d "$repo_root/src/ai_skills_engine" ]]; then
  exec python3 scripts/generate_skills_manifest.py "$@"
fi

# shellcheck source=scripts/lib/ensure-uv.sh
source "$tooling_root/scripts/lib/ensure-uv.sh"
ensure_uv

uv run --locked --no-dev python scripts/generate_skills_manifest.py "$@"
