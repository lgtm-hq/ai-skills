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

# shellcheck source=scripts/tool-versions.sh
source "$tooling_root/scripts/tool-versions.sh"
# shellcheck source=scripts/lib/fetch-verified.sh
source "$tooling_root/scripts/lib/fetch-verified.sh"

if ! command -v uv >/dev/null 2>&1; then
  manifest_tmp=$(mktemp -d)
  trap 'rm -rf "$manifest_tmp"' EXIT
  fetch_verified "$UV_INSTALLER_URL" "$UV_INSTALLER_SHA256" "$manifest_tmp/uv-install.sh"
  sh "$manifest_tmp/uv-install.sh"
  export PATH="${HOME}/.local/bin:${PATH}"
fi

uv run --locked --no-dev python scripts/generate_skills_manifest.py "$@"
